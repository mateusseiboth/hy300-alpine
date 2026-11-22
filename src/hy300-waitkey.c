/*
 * hy300-waitkey: espera alguém apertar uma tecla, com prazo. Usado pelo autoboot da
 * recuperação do HY300 para decidir entre ficar no Alpine e ir para o Android.
 *
 * Uso: hy300-waitkey SEGUNDOS [dispositivo...]
 *   sem dispositivos, abre todos os /dev/input/event* (controle IR, teclas do painel e de
 *   energia, receptor 2.4G, teclado USB).
 *
 * Saída, uma linha por vez: os segundos que faltam ("5", "4", ...), e no fim
 * "tecla <código>" (código de saída 0; o código é o KEY_* do linux/input-event-codes.h) ou
 * "tempo" (código de saída 1). Código de saída 2 para argumentos inválidos. O menu da
 * recuperação usa o código para navegar (setas, OK do controle = KEY_REPLY, Enter).
 *
 * Conta como tecla um EV_KEY com valor diferente de zero (apertar ou repetir). Movimento do
 * acelerômetro (EV_ABS) e soltar tecla não contam. Uma tecla já segurada quando o programa
 * abre o dispositivo também conta (EVIOCGKEY): dá para ligar o aparelho segurando OK.
 */
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <limits.h>
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

/* Código da primeira tecla segurada no dispositivo, ou 0. */
static int read_held_key(int fd)
{
	unsigned char keys[KEY_MAX / 8 + 1];
	int code;

	memset(keys, 0, sizeof(keys));
	if (ioctl(fd, EVIOCGKEY(sizeof(keys)), keys) < 0)
		return 0;
	for (code = 1; code <= KEY_MAX; code++)
		if (keys[code / 8] & (1 << (code % 8)))
			return code;
	return 0;
}

static int open_device(const char *path, struct pollfd *slot)
{
	int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);

	if (fd < 0)
		return 0;
	slot->fd = fd;
	slot->events = POLLIN;
	slot->revents = 0;
	return 1;
}

static int open_default_devices(struct pollfd *fds)
{
	glob_t found;
	size_t i;
	int count = 0;

	if (glob("/dev/input/event*", 0, NULL, &found) != 0)
		return 0;
	for (i = 0; i < found.gl_pathc && count < MAX_DEVICES; i++)
		count += open_device(found.gl_pathv[i], &fds[count]);
	globfree(&found);
	return count;
}

static int open_listed_devices(int argc, char **argv, struct pollfd *fds)
{
	int i, count = 0;

	for (i = 0; i < argc && count < MAX_DEVICES; i++)
		count += open_device(argv[i], &fds[count]);
	return count;
}

/* Código da primeira tecla apertada (ou repetida) entre os eventos, ou 0. */
static int find_key_press(const struct input_event *events, size_t count)
{
	size_t i;

	for (i = 0; i < count; i++)
		if (events[i].type == EV_KEY && events[i].value != 0 && events[i].code != 0)
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

static void close_device(struct pollfd *slot)
{
	close(slot->fd);
	slot->fd = -1;
}

/* Código da tecla apertada durante a espera, ou 0. */
static int poll_devices(struct pollfd *fds, int count, int timeout_ms)
{
	int i, state;

	if (poll(fds, (nfds_t)count, timeout_ms) <= 0)
		return 0;
	for (i = 0; i < count; i++) {
		if (fds[i].fd < 0 || !(fds[i].revents & (POLLIN | POLLHUP | POLLERR)))
			continue;
		state = read_device(&fds[i]);
		if (state > 0)
			return state;
		if (state < 0)
			close_device(&fds[i]);
	}
	return 0;
}

static int read_held_key_on_any(struct pollfd *fds, int count)
{
	int i, code;

	for (i = 0; i < count; i++) {
		code = read_held_key(fds[i].fd);
		if (code)
			return code;
	}
	return 0;
}

static int finish_with_key(int key)
{
	printf("tecla %d\n", key);
	fflush(stdout);
	return 0;
}

static int finish_with_timeout(void)
{
	printf("tempo\n");
	fflush(stdout);
	return 1;
}

int main(int argc, char **argv)
{
	struct pollfd fds[MAX_DEVICES];
	long seconds, remaining;
	long long deadline, now, next_tick;
	int count, key;

	if (argc < 2 || !parse_seconds(argv[1], &seconds)) {
		fprintf(stderr, "uso: %s SEGUNDOS [dispositivo...]\n", argv[0]);
		return 2;
	}
	count = argc > 2 ? open_listed_devices(argc - 2, argv + 2, fds) : open_default_devices(fds);
	key = read_held_key_on_any(fds, count);
	if (key)
		return finish_with_key(key);
	deadline = read_now_ms() + seconds * 1000;
	for (remaining = seconds; remaining > 0; remaining--) {
		printf("%ld\n", remaining);
		fflush(stdout);
		next_tick = deadline - (remaining - 1) * 1000;
		while ((now = read_now_ms()) < next_tick) {
			key = poll_devices(fds, count, (int)(next_tick - now));
			if (key)
				return finish_with_key(key);
		}
	}
	return finish_with_timeout();
}
