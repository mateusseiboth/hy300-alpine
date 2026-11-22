# Partições do eMMC por nome e o BCB da misc. Shell POSIX (tests/test_partitions.py).
#
# O kernel expõe o nome GPT de cada partição em /sys/class/block/<dev>/uevent (PARTNAME). A
# recuperação cria /dev/block/by-name/<nome> como no Android, para os mesmos comandos valerem
# nos dois sistemas.
#
# A misc começa com o bootloader_message do AOSP (2048 bytes; os 32 primeiros são o comando).
# Com "boot-recovery" ali o U-Boot sobe a partição recovery em todo boot, até alguém apagar.
# Só esses 2048 bytes são apagados, e só com esse comando: em 0x800 ficam os dados A/B da
# Rockchip e em 16 KiB um BCB legado de fábrica que o U-Boot ignora (ver hy300-rk3566,
# docs/kernel-6.1.md).
# shellcheck shell=sh

: "${HY300_SYSFS_BLOCK:=/sys/class/block}"
: "${HY300_BY_NAME:=/dev/block/by-name}"
BCB_SIZE=2048
BCB_COMMAND_SIZE=32
MISC_SECTORS=8192
SECTOR_SIZE=512

read_partname() {
	sed -n 's/^PARTNAME=//p' "$1" 2>/dev/null
}

find_partition_by_name() {
	for uevent in "$HY300_SYSFS_BLOCK"/*/uevent; do
		[ "$(read_partname "$uevent")" = "$1" ] || continue
		basename "$(dirname "$uevent")"
		return 0
	done
	return 1
}

link_partitions_by_name() {
	mkdir -p "$HY300_BY_NAME"
	for uevent in "$HY300_SYSFS_BLOCK"/*/uevent; do
		name=$(read_partname "$uevent")
		[ -n "$name" ] || continue
		ln -sfn "/dev/$(basename "$(dirname "$uevent")")" "$HY300_BY_NAME/$name"
	done
}

# Uma linha por partição com nome: "<nome> <dispositivo> <bytes>", em ordem de nome.
list_partitions() {
	for uevent in "$HY300_SYSFS_BLOCK"/*/uevent; do
		name=$(read_partname "$uevent")
		[ -n "$name" ] || continue
		dir=$(dirname "$uevent")
		echo "$name $(basename "$dir") $(($(cat "$dir/size") * SECTOR_SIZE))"
	done | sort
}

is_misc_size_expected() {
	[ "$(cat "$HY300_SYSFS_BLOCK/$1/size" 2>/dev/null)" = "$MISC_SECTORS" ]
}

wait_for_partition() {
	remaining=$2
	while :; do
		find_partition_by_name "$1" && return 0
		[ "$remaining" -gt 0 ] || return 1
		remaining=$((remaining - 1))
		sleep 1
	done
}

read_bcb_command() {
	{ dd if="$1" bs="$BCB_COMMAND_SIZE" count=1 2>/dev/null; echo; } | tr '\000' '\n' | head -n 1
}

is_recovery_command() {
	case "$1" in
	boot-recovery*) return 0 ;;
	esac
	return 1
}

clear_bcb_if_recovery() {
	[ -e "$1" ] || { echo "misc: $1 não existe"; return 1; }
	bcb_command=$(read_bcb_command "$1")
	is_recovery_command "$bcb_command" || { echo "misc: comando '$bcb_command' mantido"; return 1; }
	dd if=/dev/zero of="$1" bs="$BCB_SIZE" count=1 conv=notrunc,fsync 2>/dev/null ||
		{ echo "misc: falha ao apagar '$bcb_command'"; return 1; }
	sync
	echo "misc: comando '$bcb_command' apagado"
}
