#!/usr/bin/env bash
# Do Android para o Alpine, ficando lá sem ninguém no teclado (para gravar coisas por SSH).
#
# Grava a marca de "ficar" na misc (16 bytes em 0x10000: "hy300-ficar\0" + versão 1), só se a
# área estiver zerada ou já tiver a marca, confere lendo de volta e reinicia para onde o Alpine
# estiver. O Alpine apaga a marca ao subir (uso único) e fica no ar sem contagem.
#
# Uso: scripts/reboot-to-alpine.sh [--alpine-in boot|recovery] [--dry-run]
#   sem --alpine-in, procura hy300.slot= na cmdline do cabeçalho da boot e da recovery.
#   Alpine na boot: reboot normal. Alpine na recovery: scripts/reboot-to-test-slot.sh do
#   hy300-rk3566 (registrador do reboot-mode, nunca o BCB), com TEST_IMAGE apontando para a
#   recovery-alpine.img.
#   Sem adb root (LineageOS do HY300), dispara o gatilho debug.hy300.alpine=1, e o próprio
#   Lineage grava a marca e reinicia.
# Variáveis: HY300_RK3566 (~/hy300-handoff/hy300-rk3566), HY300_RECOVERY_IMAGE
#   (~/hy300-work/alpine/recovery-alpine.img), HY300_REBOOT_TO_TEST_SLOT (script do reboot).
set -euo pipefail

HY300_RK3566="${HY300_RK3566:-$HOME/hy300-handoff/hy300-rk3566}"
RECOVERY_IMAGE="${HY300_RECOVERY_IMAGE:-$HOME/hy300-work/alpine/recovery-alpine.img}"
REBOOT_TO_TEST_SLOT="${HY300_REBOOT_TO_TEST_SLOT:-$HY300_RK3566/scripts/reboot-to-test-slot.sh}"
BY_NAME=/dev/block/by-name
MISC=$BY_NAME/misc
MARK_INDEX=4096 # 0x10000 / 16
MARK_HEX=68793330302d66696361720001000000
ZERO_HEX=00000000000000000000000000000000
TMP=/data/local/tmp/hy300-ficar.bin

alpine_in=
dry_run=

fail() {
	echo "$1"
	exit 1
}

parse_args() {
	while (($# > 0)); do
		case "$1" in
		--alpine-in) alpine_in="${2:-}"; shift ;;
		--dry-run) dry_run=1 ;;
		*) sed -n '2,17s/^# \{0,1\}//p' "$0"; exit 2 ;;
		esac
		shift
	done
	[[ -z "$alpine_in" || "$alpine_in" == boot || "$alpine_in" == recovery ]] || fail "--alpine-in: boot ou recovery"
}

# hy300.slot=<parte> na cmdline do cabeçalho (64 bytes depois do início, 512 de comprimento).
has_alpine_header() {
	local count
	count="$(adb shell "dd if=$BY_NAME/$1 bs=64 skip=1 count=8 2>/dev/null | tr -d '\\000' | grep -c hy300.slot=$1" | tr -d '\r')"
	[[ "${count:-0}" -gt 0 ]]
}

find_alpine() {
	[[ -n "$alpine_in" ]] && { echo "$alpine_in"; return; }
	has_alpine_header boot && { echo boot; return; }
	has_alpine_header recovery && { echo recovery; return; }
	fail "não achei o Alpine nem na boot nem na recovery (hy300.slot= no cabeçalho); use --alpine-in"
}

read_mark_area() {
	adb shell "dd if=$MISC bs=16 skip=$MARK_INDEX count=1 2>/dev/null | od -An -v -tx1" | tr -d ' \r\n'
}

write_mark() {
	local mark
	mark="$(mktemp)"
	printf 'hy300-ficar\000\001\000\000\000' >"$mark"
	adb push "$mark" "$TMP" >/dev/null
	rm -f "$mark"
	adb shell "dd if=$TMP of=$MISC bs=16 seek=$MARK_INDEX count=1 conv=notrunc,fsync 2>/dev/null; sync; rm -f $TMP"
	[[ "$(read_mark_area)" == "$MARK_HEX" ]] || fail "FALHOU: a marca não conferiu depois de gravar"
}

is_adb_root() {
	[[ "$(adb shell id -u | tr -d '\r')" == 0 ]]
}

# Sem adb root (userdebug do LineageOS, ro.debuggable=0): o serviço hy300-alpine do Lineage grava
# a mesma marca e faz o reboot normal quando o shell seta debug.hy300.alpine=1.
use_lineage_trigger() {
	echo ">> sem adb root: usando o gatilho do LineageOS (debug.hy300.alpine=1)"
	[[ -n "$dry_run" ]] && { echo "dry-run: gatilho não disparado"; return; }
	adb shell setprop debug.hy300.alpine 1
	echo ">> pedido feito; o Lineage grava a marca e reinicia (a conexão adb cai agora)"
}

reboot_to() {
	[[ "$1" == boot ]] && { adb shell reboot; return; }
	TEST_IMAGE="$RECOVERY_IMAGE" "$REBOOT_TO_TEST_SLOT"
}

main() {
	parse_args "$@"
	adb root >/dev/null
	sleep "${HY300_ADB_ROOT_WAIT:-3}"
	adb wait-for-device
	is_adb_root || { use_lineage_trigger; return; }
	local place area
	place="$(find_alpine)"
	area="$(read_mark_area)"
	[[ "$area" == "$ZERO_HEX" || "$area" == "$MARK_HEX" ]] || fail "a área da marca na misc (0x10000) não está zerada ($area); nada gravado"
	echo ">> Alpine na $place"
	[[ -n "$dry_run" ]] && { echo "dry-run: marca e reboot não feitos"; return; }
	write_mark
	echo ">> marca gravada; reiniciando para o Alpine (a conexão adb cai agora)"
	reboot_to "$place"
}

main "$@"
