/*
 * hy300-waitkey: espera alguém apertar uma tecla do TECLADO, com prazo. Usado pelo autoboot da
 * recuperação do HY300 para decidir entre ficar no Alpine e ir para o Android.
 *
 * Uso: hy300-waitkey [--all] SEGUNDOS [dispositivo...]
 *      hy300-waitkey --classify NOME CÓDIGO...     (só para os testes)
 *   sem dispositivos, abre os /dev/input/event* que forem teclados (abaixo).
 *   --all aceita qualquer dispositivo listado (os testes usam arquivos, sem ioctl).
 *
 * Saída, uma linha por vez: os segundos que faltam ("5", "4", ...), e no fim
 * "tecla <código> <ms desde o início> <dispositivo>" (saída 0) ou "tempo" (saída 1). Saída 2
 * para argumentos inválidos.
 *
 * Só conta EV_KEY com valor 1 (apertar; soltar e repetir não), com código de tecla de teclado
 * (KEY_ESC a KEY_MICMUTE; BTN_* do mouse não), de um teclado de verdade: nome fora da lista de
 * ignorados (receptor IR, teclas do painel e de energia, mouse, Consumer/System Control do
 * receptor 2.4G) e com letras no mapa de teclas. No aparelho o receptor IR capta ruído, e sem
 * esse filtro o autoboot ficava no Alpine sozinho. Eventos de antes da abertura não chegam.
 */
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/input.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define MAX_DEVICES 32
#define EVENTS_PER_READ 64
#define NAME_SIZE 128
#define KEY_BYTES (KEY_MAX / 8 + 1)

struct device {
	struct pollfd *poll;
	char name[NAME_SIZE];
};

static const char *const IGNORED_NAMES[] = {
	"pwm", "adc-keys", "gpio-keys", "powerkey", "mouse", "consumer control", "system control",
};

/* Letras e espaço/Enter: o que um controle, um mouse ou teclas multimídia não têm. */
static const int KEYBOARD_KEYS[] = {
	KEY_Q, KEY_W, KEY_E, KEY_R, KEY_T, KEY_A, KEY_S, KEY_D, KEY_F, KEY_G,
	KEY_Z, KEY_X, KEY_C, KEY_V, KEY_B, KEY_SPACE, KEY_ENTER,
};

static long long read_now_ms(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int parse_seconds(const char *text, long *seconds)
{
	char *end;

	errno = 0;
	*seconds = strtol(text, &end, 10);
	return errno == 0 && end != text && *end == '\0' && *seconds >= 0 && *seconds <= 3600;
}

static int is_ignored_name(const char *name)
{
	char lower[NAME_SIZE];
	size_t i;

	for (i = 0; i + 1 < sizeof(lower) && name[i]; i++)
		lower[i] = (char)tolower((unsigned char)name[i]);
	lower[i] = '\0';
	for (i = 0; i < sizeof(IGNORED_NAMES) / sizeof(IGNORED_NAMES[0]); i++)
		if (strstr(lower, IGNORED_NAMES[i]))
			return 1;
	return 0;
}

static int has_key(const unsigned char *bits, int code)
{
	return code >= 0 && code <= KEY_MAX && (bits[code / 8] & (1 << (code % 8)));
}

static int has_keyboard_keys(const unsigned char *bits)
{
	size_t i;

	for (i = 0; i < sizeof(KEYBOARD_KEYS) / sizeof(KEYBOARD_KEYS[0]); i++)
		if (!has_key(bits, KEYBOARD_KEYS[i]))
			return 0;
	return 1;
}

static int is_keyboard(const char *name, const unsigned char *bits)
{
	return !is_ignored_name(name) && has_keyboard_keys(bits);
}

static int is_keyboard_key(int code)
{
	return code >= KEY_ESC && code <= KEY_MICMUTE;
}

static void read_device_name(int fd, const char *path, char *name)
{
	if (ioctl(fd, EVIOCGNAME(NAME_SIZE - 1), name) < 0)
		snprintf(name, NAME_SIZE, "%s", path);
	name[NAME_SIZE - 1] = '\0';
}

static int is_keyboard_device(int fd, const char *name)
{
	unsigned char bits[KEY_BYTES];

	memset(bits, 0, sizeof(bits));
	if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(bits)), bits) < 0)
		return 0;
	return is_keyboard(name, bits);
}

static int open_device(const char *path, int accept_all, struct pollfd *slot, struct device *device)
{
	int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);

	if (fd < 0)
		return 0;
	read_device_name(fd, path, device->name);
	if (!accept_all && !is_keyboard_device(fd, device->name)) {
		close(fd);
		return 0;
	}
	slot->fd = fd;
	slot->events = POLLIN;
	slot->revents = 0;
	device->poll = slot;
	return 1;
}

static int open_devices(char **paths, size_t count, int accept_all, struct pollfd *fds, struct device *devices)
{
	size_t i;
	int opened = 0;

	for (i = 0; i < count && opened < MAX_DEVICES; i++)
		opened += open_device(paths[i], accept_all, &fds[opened], &devices[opened]);
	return opened;
}

static int open_default_devices(struct pollfd *fds, struct device *devices)
{
	glob_t found;
	int opened;

	if (glob("/dev/input/event*", 0, NULL, &found) != 0)
		return 0;
	opened = open_devices(found.gl_pathv, found.gl_pathc, 0, fds, devices);
	globfree(&found);
	return opened;
}

/* Código da primeira tecla de teclado apertada entre os eventos, ou 0. */
static int find_key_press(const struct input_event *events, size_t count)
{
	size_t i;

	for (i = 0; i < count; i++)
		if (events[i].type == EV_KEY && events[i].value == 1 && is_keyboard_key(events[i].code))
			return events[i].code;
	return 0;
}

/* >0: código da tecla; 0: nada; -1: dispositivo acabou (removido, ou fim de arquivo nos testes). */
static int read_device(struct pollfd *slot)
{
	struct input_event events[EVENTS_PER_READ];
	ssize_t got = read(slot->fd, events, sizeof(events));

	if (got > 0)
		return find_key_press(events, (size_t)got / sizeof(events[0]));
	if (got < 0 && (errno == EAGAIN || errno == EINTR))
		return 0;
	return -1;
}

/* Índice do dispositivo onde uma tecla foi apertada durante a espera (e o código), ou -1. */
static int poll_devices(struct pollfd *fds, int count, int timeout_ms, int *key)
{
	int i, state;

	if (poll(fds, (nfds_t)count, timeout_ms) <= 0)
		return -1;
	for (i = 0; i < count; i++) {
		if (fds[i].fd < 0 || !(fds[i].revents & (POLLIN | POLLHUP | POLLERR)))
			continue;
		state = read_device(&fds[i]);
		if (state > 0) {
			*key = state;
			return i;
		}
		if (state < 0) {
			close(fds[i].fd);
			fds[i].fd = -1;
		}
	}
	return -1;
}

static int finish_with_key(int key, long long elapsed_ms, const char *device)
{
	printf("tecla %d %lld %s\n", key, elapsed_ms, device);
	fflush(stdout);
	return 0;
}

static int finish_with_timeout(void)
{
	printf("tempo\n");
	fflush(stdout);
	return 1;
}

static int run_classify(int argc, char **argv)
{
	unsigned char bits[KEY_BYTES];
	int i, code;

	memset(bits, 0, sizeof(bits));
	for (i = 1; i < argc; i++) {
		code = atoi(argv[i]);
		if (code >= 0 && code <= KEY_MAX)
			bits[code / 8] |= (unsigned char)(1 << (code % 8));
	}
	printf("%s\n", is_keyboard(argv[0], bits) ? "teclado" : "ignorado");
	return 0;
}

static int wait_for_key(long seconds, struct pollfd *fds, struct device *devices, int count)
{
	long long start = read_now_ms(), deadline = start + seconds * 1000, next_tick, now;
	long remaining;
	int key = 0, index;

	for (remaining = seconds; remaining > 0; remaining--) {
		printf("%ld\n", remaining);
		fflush(stdout);
		next_tick = deadline - (remaining - 1) * 1000;
		while ((now = read_now_ms()) < next_tick) {
			index = poll_devices(fds, count, (int)(next_tick - now), &key);
			if (index >= 0)
				return finish_with_key(key, read_now_ms() - start, devices[index].name);
		}
	}
	return finish_with_timeout();
}

int main(int argc, char **argv)
{
	struct pollfd fds[MAX_DEVICES];
	struct device devices[MAX_DEVICES];
	int accept_all = 0, first = 1, count;
	long seconds;

	if (argc >= 3 && strcmp(argv[1], "--classify") == 0)
		return run_classify(argc - 2, argv + 2);
	if (argc >= 2 && strcmp(argv[1], "--all") == 0) {
		accept_all = 1;
		first = 2;
	}
	if (argc <= first || !parse_seconds(argv[first], &seconds)) {
		fprintf(stderr, "uso: %s [--all] SEGUNDOS [dispositivo...]\n", argv[0]);
		return 2;
	}
	count = argc > first + 1 ? open_devices(argv + first + 1, (size_t)(argc - first - 1), accept_all, fds, devices)
				 : open_default_devices(fds, devices);
	return wait_for_key(seconds, fds, devices, count);
}
