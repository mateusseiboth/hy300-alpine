# Leitura de boot.img Android, header v0 a v2 (o formato que o U-Boot do HY300 usa). Shell
# POSIX com od/dd/head do busybox (tests/test_kexec.py).
#
# Layout: header numa página; depois kernel, ramdisk, second (resource.img da Rockchip),
# recovery_dtbo (v1+) e dtb (v2), cada um começando numa página nova. Campos (little-endian):
# tamanhos do kernel em 8, ramdisk em 16, second em 24, página em 36, versão em 40; cmdline
# em 64 (512 bytes) e o resto dela em 608 (1024 bytes); recovery_dtbo em 1632; dtb em 1648.
# shellcheck shell=sh

read_u32() {
	od -An -tu4 -j "$2" -N4 "$1" 2>/dev/null | tr -d ' \n'
}

read_cstr() {
	dd if="$1" bs=1 skip="$2" count="$3" 2>/dev/null | tr '\000' '\n' | head -n 1
}

is_android_bootimg() {
	[ "$(dd if="$1" bs=8 count=1 2>/dev/null)" = "ANDROID!" ]
}

# Define BOOTIMG_VERSION, BOOTIMG_PAGE, BOOTIMG_*_SIZE e BOOTIMG_CMDLINE.
read_bootimg() {
	[ -f "$1" ] || { echo "$1 não existe"; return 1; }
	is_android_bootimg "$1" || { echo "$1 não é um boot.img Android"; return 1; }
	BOOTIMG_VERSION=$(read_u32 "$1" 40)
	case "$BOOTIMG_VERSION" in
	0 | 1 | 2) ;;
	*) echo "header v$BOOTIMG_VERSION não suportado (só v0 a v2)"; return 1 ;;
	esac
	BOOTIMG_KERNEL_SIZE=$(read_u32 "$1" 8)
	BOOTIMG_RAMDISK_SIZE=$(read_u32 "$1" 16)
	BOOTIMG_SECOND_SIZE=$(read_u32 "$1" 24)
	BOOTIMG_PAGE=$(read_u32 "$1" 36)
	BOOTIMG_RECOVERY_DTBO_SIZE=0
	BOOTIMG_DTB_SIZE=0
	[ "$BOOTIMG_VERSION" -ge 1 ] && BOOTIMG_RECOVERY_DTBO_SIZE=$(read_u32 "$1" 1632)
	[ "$BOOTIMG_VERSION" -ge 2 ] && BOOTIMG_DTB_SIZE=$(read_u32 "$1" 1648)
	BOOTIMG_CMDLINE="$(read_cstr "$1" 64 512)$(read_cstr "$1" 608 1024)"
	[ "$BOOTIMG_PAGE" -gt 0 ] || { echo "página de tamanho zero"; return 1; }
	[ "$BOOTIMG_KERNEL_SIZE" -gt 0 ] || { echo "boot.img sem kernel"; return 1; }
}

count_pages() {
	echo $((($1 + BOOTIMG_PAGE - 1) / BOOTIMG_PAGE))
}

copy_section() {
	[ "$3" -gt 0 ] || return 0
	dd if="$1" bs="$BOOTIMG_PAGE" skip="$2" count="$(count_pages "$3")" 2>/dev/null | head -c "$3" >"$4"
}

# Extrai kernel, ramdisk e dtb para o diretório $2 (depois de read_bootimg).
extract_bootimg() {
	mkdir -p "$2" || return 1
	kernel_page=1
	ramdisk_page=$((kernel_page + $(count_pages "$BOOTIMG_KERNEL_SIZE")))
	second_page=$((ramdisk_page + $(count_pages "$BOOTIMG_RAMDISK_SIZE")))
	dtbo_page=$((second_page + $(count_pages "$BOOTIMG_SECOND_SIZE")))
	dtb_page=$((dtbo_page + $(count_pages "$BOOTIMG_RECOVERY_DTBO_SIZE")))
	rm -f "$2/kernel" "$2/ramdisk" "$2/dtb"
	copy_section "$1" "$kernel_page" "$BOOTIMG_KERNEL_SIZE" "$2/kernel" &&
		copy_section "$1" "$ramdisk_page" "$BOOTIMG_RAMDISK_SIZE" "$2/ramdisk" &&
		copy_section "$1" "$dtb_page" "$BOOTIMG_DTB_SIZE" "$2/dtb"
}
