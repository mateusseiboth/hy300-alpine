# Watchdog de hardware do RK3566 (dw_wdt). Shell POSIX (tests/test_kexec.py, test_watchdog.py).
#
# O kernel do HY300 arma o watchdog no começo do boot (CONFIG_HY300_EARLY_BEACON, ~89 s) e
# ninguém o alimenta até a recuperação abrir o /dev/watchdog. O hy300-watchdogd fica sempre no
# ar (o init o reinicia se morrer, o OOM killer não o escolhe) e liga o pré-timeout: um
# travamento de WATCHDOG_TIMEOUT segundos vira panic e reinício normal; só se nem a interrupção
# for atendida vem o reset de hardware, um prazo depois (o beacon do kernel o faz reiniciar em
# vez de desligar, pelo CRU_GLB_RST_CON).
# shellcheck shell=sh

: "${HY300_WATCHDOG_DEV:=/dev/watchdog}"
WATCHDOG_DAEMON=hy300-watchdogd
WATCHDOG_TIMEOUT=30
WATCHDOG_PRETIMEOUT=30
WATCHDOG_FEED_EVERY=10
# Maior prazo do dw_wdt com o clock de 24 MHz (2^31 ciclos).
WATCHDOG_MAX_TIMEOUT=89

is_watchdog_off() {
	[ -e "$HY300_RUN/watchdog-off" ]
}

wait_for_watchdog_exit() {
	remaining=$1
	while :; do
		alive=
		for pid in $(pidof "$WATCHDOG_DAEMON"); do
			kill -0 "$pid" 2>/dev/null && alive=1
		done
		[ -z "$alive" ] && return 0
		[ "$remaining" -gt 0 ] || return 1
		remaining=$((remaining - 1))
		sleep 1
	done
}

# Antes de passar o aparelho a outro sistema (kexec -e, ou reboot para o Android): o init não
# pode reabrir o watchdog (arquivo watchdog-off), o daemon sai
# com o fechamento mágico ('V'), e o último prazo programado fica o maior possível, em modo de
# reset (sem pré-timeout: no kernel novo ninguém atende a interrupção até o driver subir). Se o
# driver conseguir parar o watchdog, o kernel novo sobe sem ele; se não, o kernel atual segue
# alimentando até o kexec, e o kernel novo tem até ~89 s para assumir.
prepare_watchdog_for_handoff() {
	mkdir -p "$HY300_RUN"
	: >"$HY300_RUN/watchdog-off"
	for pid in $(pidof "$WATCHDOG_DAEMON"); do
		kill -TERM "$pid"
	done
	wait_for_watchdog_exit 5 || echo "watchdog: o daemon não saiu"
	[ -c "$HY300_WATCHDOG_DEV" ] || return 0
	"$WATCHDOG_DAEMON" -T "$WATCHDOG_MAX_TIMEOUT" -P 0 -t 1 "$HY300_WATCHDOG_DEV" 2>/dev/null &
	sleep 1
	for pid in $(pidof "$WATCHDOG_DAEMON"); do
		kill -TERM "$pid"
	done
	wait_for_watchdog_exit 5 || echo "watchdog: o daemon não saiu"
}
