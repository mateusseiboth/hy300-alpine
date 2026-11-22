# Marca de "ficar no Alpine" de uso único na misc. Shell POSIX (tests/test_misc_mark.py).
#
# 16 bytes no offset 0x10000 da misc (4 MiB): "hy300-ficar\0" + versão 1 (01 00 00 00). Na misc
# de fábrica só há dados em 0x0-0xfff (BCB do AOSP e dados A/B da Rockchip em 0x800) e em
# 0x4000 (BCB legado, que o U-Boot ignora); de 0x8000 em diante é zero. Quem grava: o
# scripts/reboot-to-alpine.sh (pelo Android) e o hy300-ficar (no Alpine). Quem apaga: o estágio 1
# do Alpine, antes de qualquer outra coisa, para não virar laço. Só o valor exato vale.
# Roda também no estágio 1 (busybox estático do initramfs).
# shellcheck shell=sh

STAY_MARK_BLOCK=16
STAY_MARK_INDEX=4096	# 0x10000 / 16
STAY_MARK_HEX=68793330302d666963617200 # "hy300-ficar\0"
STAY_MARK_HEX=${STAY_MARK_HEX}01000000 # versão 1

read_stay_area_hex() {
	dd if="$1" bs="$STAY_MARK_BLOCK" skip="$STAY_MARK_INDEX" count=1 2>/dev/null | od -An -v -tx1 | tr -d ' \n'
}

is_stay_mark_present() {
	[ "$(read_stay_area_hex "$1")" = "$STAY_MARK_HEX" ]
}

is_stay_area_zero() {
	[ "$(read_stay_area_hex "$1")" = "00000000000000000000000000000000" ]
}

clear_stay_mark() {
	dd if=/dev/zero of="$1" bs="$STAY_MARK_BLOCK" seek="$STAY_MARK_INDEX" count=1 conv=notrunc,fsync 2>/dev/null || return 1
	sync
	is_stay_area_zero "$1"
}

# Grava só se a área estiver zerada ou já tiver a marca, e confere lendo de volta.
write_stay_mark() {
	is_stay_mark_present "$1" || is_stay_area_zero "$1" ||
		{ echo "a área da marca na misc (0x10000) não está zerada: nada gravado"; return 1; }
	printf 'hy300-ficar\000\001\000\000\000' |
		dd of="$1" bs="$STAY_MARK_BLOCK" seek="$STAY_MARK_INDEX" count=1 conv=notrunc,fsync 2>/dev/null || return 1
	sync
	is_stay_mark_present "$1" || { echo "a marca não conferiu depois de gravar"; return 1; }
}

# Contador de boots falhos, logo depois da marca: 16 bytes em 0x10010, "hy300-boots\0" +
# contagem (1 byte) + 3 zeros; zero em tudo é contagem 0. O estágio 1 soma um no começo de cada
# boot e o autoboot zera quando o Alpine fica pronto. Se o Alpine não chega a ficar pronto
# BOOT_FAILURE_LIMIT vezes seguidas, o estágio 1 zera e vai uma vez para o Android: o laço de
# um Alpine quebrado termina, e qualquer outra falha (panic, watchdog) volta para o Alpine.
BOOT_COUNTER_INDEX=4097	# 0x10010 / 16
BOOT_COUNTER_PREFIX_HEX=6879333030 # "hy300"
BOOT_COUNTER_PREFIX_HEX=${BOOT_COUNTER_PREFIX_HEX}2d626f6f747300 # "-boots\0"

read_counter_hex() {
	dd if="$1" bs="$STAY_MARK_BLOCK" skip="$BOOT_COUNTER_INDEX" count=1 2>/dev/null | od -An -v -tx1 | tr -d ' \n'
}

# Imprime a contagem; falha se a área tiver outra coisa (não mexemos no que não é nosso).
read_boot_failures() {
	hex=$(read_counter_hex "$1")
	[ "$hex" = "00000000000000000000000000000000" ] && { echo 0; return 0; }
	case "$hex" in
	"$BOOT_COUNTER_PREFIX_HEX"??000000) echo $((0x$(echo "$hex" | cut -c25-26))) ;;
	*) return 1 ;;
	esac
}

write_boot_failures() {
	[ "$2" -gt 0 ] || { dd if=/dev/zero of="$1" bs="$STAY_MARK_BLOCK" seek="$BOOT_COUNTER_INDEX" count=1 conv=notrunc,fsync 2>/dev/null; sync; return; }
	printf "hy300-boots\\000\\$(printf %03o "$2")\\000\\000\\000" |
		dd of="$1" bs="$STAY_MARK_BLOCK" seek="$BOOT_COUNTER_INDEX" count=1 conv=notrunc,fsync 2>/dev/null
	sync
}

clear_boot_failures() {
	write_boot_failures "$1" 0
}

# No começo do boot: imprime a nova contagem, ou "android" quando o limite foi atingido (e zera).
register_boot_attempt() {
	failures=$(read_boot_failures "$1") || { echo "área do contador na misc com outros dados"; return 1; }
	[ "$failures" -ge "$2" ] && { clear_boot_failures "$1"; echo android; return 0; }
	write_boot_failures "$1" $((failures + 1))
	echo $((failures + 1))
}
