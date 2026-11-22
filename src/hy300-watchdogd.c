/*
 * hy300-watchdogd: alimenta o watchdog de hardware do HY300 com pré-timeout.
 *
 * Uso: hy300-watchdogd [-T prazo] [-P pré-timeout] [-t intervalo] DISPOSITIVO
 *   padrões: -T 30 -P 30 -t 10 (segundos); -P 0 desliga o pré-timeout.
 *
 * Com o pré-timeout o dw_wdt do RK3566 fica no modo de interrupção: no fim do prazo vem uma
 * interrupção, o governador "panic" (CONFIG_WATCHDOG_PRETIMEOUT_GOV_PANIC) dá panic e o
 * aparelho reinicia pelo caminho normal, com o log no pstore. Só se nem a interrupção for
 * atendida (todas as CPUs travadas) o reset de hardware acontece, um prazo depois. O busybox
 * watchdog não sabe pedir o pré-timeout.
 *
 * Sai com o fechamento mágico ('V') em SIGTERM, SIGINT ou SIGHUP. Se o ioctl de alimentar
 * falhar, alimenta escrevendo no dispositivo, que o driver também aceita.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/watchdog.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define MAX_SECONDS 3600

static volatile sig_atomic_t stop_requested;

static void request_stop(int signo)
{
	(void)signo;
	stop_requested = 1;
}

static int parse_seconds(const char *text, int min, int *value)
{
	char *end;
	long parsed;

	errno = 0;
	parsed = strtol(text, &end, 10);
	if (errno || end == text || *end || parsed < min || parsed > MAX_SECONDS)
		return 0;
	*value = (int)parsed;
	return 1;
}

static int parse_args(int argc, char **argv, int *timeout, int *pretimeout, int *interval)
{
	int opt;

	while ((opt = getopt(argc, argv, "T:P:t:")) != -1) {
		if (opt == 'T' && parse_seconds(optarg, 1, timeout))
			continue;
		if (opt == 'P' && parse_seconds(optarg, 0, pretimeout))
			continue;
		if (opt == 't' && parse_seconds(optarg, 1, interval))
			continue;
		return 0;
	}
	return optind == argc - 1 && *interval < *timeout;
}

static void configure(int fd, int timeout, int pretimeout)
{
	int value = timeout;

	if (ioctl(fd, WDIOC_SETTIMEOUT, &value) == 0)
		fprintf(stderr, "hy300-watchdogd: prazo %d s\n", value);
	value = pretimeout;
	if (ioctl(fd, WDIOC_SETPRETIMEOUT, &value) == 0)
		fprintf(stderr, "hy300-watchdogd: pré-timeout %d s (panic e reinício normal)\n", value);
	else
		fprintf(stderr, "hy300-watchdogd: pré-timeout indisponível (%s); só o reset de hardware\n", strerror(errno));
}

static void feed(int fd)
{
	int dummy = 0;

	if (ioctl(fd, WDIOC_KEEPALIVE, &dummy) != 0 && write(fd, "1", 1) != 1)
		fprintf(stderr, "hy300-watchdogd: falha ao alimentar: %s\n", strerror(errno));
}

static void sleep_seconds(int seconds)
{
	struct timespec left = { .tv_sec = seconds, .tv_nsec = 0 };

	while (!stop_requested && nanosleep(&left, &left) != 0 && errno == EINTR)
		;
}

static void install_handlers(void)
{
	struct sigaction action;

	memset(&action, 0, sizeof(action));
	action.sa_handler = request_stop;
	sigaction(SIGTERM, &action, NULL);
	sigaction(SIGINT, &action, NULL);
	sigaction(SIGHUP, &action, NULL);
}

int main(int argc, char **argv)
{
	int timeout = 30, pretimeout = 30, interval = 10, fd;

	if (!parse_args(argc, argv, &timeout, &pretimeout, &interval)) {
		fprintf(stderr, "uso: %s [-T prazo] [-P pré-timeout] [-t intervalo < prazo] DISPOSITIVO\n", argv[0]);
		return 2;
	}
	fd = open(argv[optind], O_WRONLY | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr, "hy300-watchdogd: %s: %s\n", argv[optind], strerror(errno));
		return 1;
	}
	install_handlers();
	configure(fd, timeout, pretimeout);
	while (!stop_requested) {
		feed(fd);
		sleep_seconds(interval);
	}
	if (write(fd, "V", 1) != 1)
		fprintf(stderr, "hy300-watchdogd: fechamento mágico falhou: %s\n", strerror(errno));
	close(fd);
	return 0;
}
