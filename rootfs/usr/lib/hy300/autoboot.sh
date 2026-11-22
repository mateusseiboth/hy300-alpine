# Decisões do autoboot: ficar no Alpine ou ir para o Android. Shell POSIX
# (tests/test_autoboot.py).
#
# O Alpine e o Android dividem as partições boot e recovery. O build grava hy300.slot=<onde o
# Alpine está> na cmdline de cada imagem; o Android está na outra:
#   Alpine na boot     -> Android na recovery: reboot(RESTART2, "recovery"), que grava o modo
#                         no registrador do PMU_GRF (o U-Boot sobe a recovery uma vez). Nunca
#                         pelo BCB da misc: o BCB sobrevive a tirar da tomada.
#   Alpine na recovery -> Android na boot: reboot normal.
# shellcheck shell=sh

: "${HY300_SYSFS_BLOCK:=/sys/class/block}"
: "${HY300_WAITKEY:=/usr/sbin/hy300-waitkey}"
AUTOBOOT_DELAY_DEFAULT=5
STAY_FILE_NAME=hy300-ficar

read_autoboot_delay() {
	read_cmdline_number hy300.autoboot "$AUTOBOOT_DELAY_DEFAULT"
}

read_android_slot() {
	case "$(read_slot)" in
	boot) echo recovery ;;
	recovery) echo boot ;;
	*) echo desconhecido ;;
	esac
}

# Motivo para ficar sem contagem; vazio se a contagem deve acontecer.
read_stay_reason() {
	[ "$1" = 0 ] && { echo "hy300.autoboot=0 na cmdline"; return; }
	[ "$2" = desconhecido ] && { echo "partição do Android desconhecida (sem hy300.slot)"; return; }
	return 0
}

# Pendrive com um arquivo hy300-ficar na raiz (qualquer partição, ou o disco sem partição).
has_usb_stay_flag() {
	mountpoint=$HY300_RUN/usb
	mkdir -p "$mountpoint"
	for uevent in "$HY300_SYSFS_BLOCK"/sd*/uevent; do
		[ -e "$uevent" ] || continue
		dev=$(basename "$(dirname "$uevent")")
		mount -o ro "/dev/$dev" "$mountpoint" 2>/dev/null || continue
		found=
		[ -e "$mountpoint/$STAY_FILE_NAME" ] && found=1
		umount "$mountpoint" 2>/dev/null
		[ -n "$found" ] && return 0
	done
	return 1
}

# Conferido no fim da contagem: o arquivo de ficar (criado por ssh, por exemplo) ou o pendrive
# (a USB leva alguns segundos para aparecer depois do boot).
read_late_stay_reason() {
	[ -e "$HY300_RUN/ficar" ] && { echo "arquivo $HY300_RUN/ficar"; return; }
	has_usb_stay_flag && { echo "pendrive com $STAY_FILE_NAME"; return; }
	return 0
}

build_countdown_text() {
	printf '\n\n  Alpine: iniciando o Android em %s s.\n\n  Aperte qualquer tecla do teclado para ficar no Alpine.\n' "$1"
}

# Folga do limite duro em volta do hy300-waitkey: a contagem nunca passa de N + folga segundos.
COUNTDOWN_SLACK=3

# "tecla <código> <ms> <dispositivo>" do hy300-waitkey vira o motivo de ficar, para o log.
build_key_reason() {
	echo "$1" | awk '{ code = $2; ms = $3; $1 = $2 = $3 = ""; sub(/^ +/, ""); printf "tecla %s aos %s ms em %s\n", code, ms, $0 }'
}

# Mostra a contagem e imprime "tecla ..." (ver build_key_reason) ou "tempo". Sem o
# hy300-waitkey, ou se ele não terminar no prazo, conta como "tempo".
run_countdown() {
	timeout "$(($1 + COUNTDOWN_SLACK))" "$HY300_WAITKEY" "$1" 2>/dev/null | while read -r word; do
		case "$word" in
		tecla*) build_key_reason "$word" ;;
		tempo) echo tempo ;;
		*) show_screen "$(build_countdown_text "$word")" ;;
		esac
	done
}

boot_android() {
	sync
	case "$1" in
	recovery) hy300-reboot-recovery ;;
	boot) reboot ;;
	*) return 1 ;;
	esac
}
