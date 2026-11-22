#!/usr/bin/env bash
# Monta do zero a recuperação Alpine do HY300: kernel 6.1 (branch hy300-6.1), dois rootfs
# Alpine aarch64 e as imagens:
#
#   backup-alpine.img     ext4 da partição backup (390070272 bytes): rootfs.sqfs do Alpine
#                         completo (núcleo, extras e ambiente gráfico), .sha256 e config/
#
# e boot.img v2 com o mesmo kernel e o mesmo initramfs (estágio 1 + o núcleo em squashfs, que é
# o modo de resgate quando a backup falta):
#
#   recovery-alpine.img   padding da partição recovery (113246208 bytes), hy300.slot=recovery
#   boot-alpine.img       padding da partição boot (41943040 bytes), hy300.slot=boot
#   recovery-alpine-image-crua.img   como a primeira, mas com a Image sem compressão (o formato
#                         já provado no U-Boot), para separar um problema da Image.gz
#
# Kernel comprimido (Image.gz): a Image crua (39,8 MiB) não cabe na boot com o initramfs.
# Resource: o de fábrica de cada partição (o U-Boot usa o rk-kernel.dtb dele); o kernel usa o
# DT embutido. Nada é gravado no aparelho.
#
# Variáveis (padrões entre parênteses):
#   KSRC (~/hy300-work/kernel-recovery-wt)   KBUILD_OUT (~/hy300-work/kbuild-recovery)
#   OUT (~/hy300-work/alpine)                BUILD_DIR (/mnt/hd/hy300-alpine/build, ou OUT/build)
#   HY300_RK3566 (~/hy300-handoff/hy300-rk3566)  FACTORY (~/hy300-backup)
#   BOOT_REF (FACTORY/estado-20261122/particoes/boot.img: a boot atual, com a splash)
#   SSH_PUBKEY (~/.ssh/id_rsa.pub)  WIFI_CREDENTIALS (~/hy300-work/wifi/credenciais.conf)
#   VENDOR_IMG (~/hy300-work/vendor.img)  AUTOBOOT (5: segundos até ir para o Android; 0 = ficar)
#   SMOKE (1: teste de fumaça no QEMU)  JOBS
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
HY300_RK3566="${HY300_RK3566:-$HOME/hy300-handoff/hy300-rk3566}"
KSRC="${KSRC:-$HOME/hy300-work/kernel-recovery-wt}"
KOUT="${KBUILD_OUT:-$HOME/hy300-work/kbuild-recovery}"
OUT="${OUT:-$HOME/hy300-work/alpine}"
DEFAULT_BUILD="$OUT/build"
[[ -d /mnt/hd && -w /mnt/hd ]] && DEFAULT_BUILD=/mnt/hd/hy300-alpine/build
BUILD="${BUILD_DIR:-$DEFAULT_BUILD}"
FACTORY="${FACTORY:-$HOME/hy300-backup}"
BOOT_REF="${BOOT_REF:-$FACTORY/estado-20261122/particoes/boot.img}"
SSH_PUBKEY="${SSH_PUBKEY:-$HOME/.ssh/id_rsa.pub}"
WIFI_CREDENTIALS="${WIFI_CREDENTIALS:-$HOME/hy300-work/wifi/credenciais.conf}"
VENDOR_IMG="${VENDOR_IMG:-$HOME/hy300-work/vendor.img}"
AUTOBOOT="${AUTOBOOT:-5}"
SMOKE="${SMOKE:-1}"
JOBS="${JOBS:-$(nproc)}"

ALPINE_VERSION=3.24.4
ALPINE_BRANCH=v3.24
CROSS=aarch64-linux-gnu-
DTB_NAME=rk3566-hy300.dtb
CONFIGS=(rockchip_linux_defconfig rk3566.config rk3566_hy300.config)
RECOVERY_SIZE=113246208
BOOT_SIZE=41943040
BACKUP_SIZE=390070272
CMDLINE="hy300.autoboot=$AUTOBOOT panic=5 console=tty0 fbcon=font:TER16x32"
# Só a imagem da boot: panic e travamento voltam pela recovery (Android), sem laço na boot.
BOOT_ONLY_CMDLINE="hy300.crash_to_recovery=1"

IMAGE="$KOUT/arch/arm64/boot/Image"
IMAGE_GZ="$BUILD/Image.gz"
DTB="$KOUT/arch/arm64/boot/dts/rockchip/$DTB_NAME"
SQUASHFS="$BUILD/rootfs-core.sqfs"
FULL_SQUASHFS="$BUILD/rootfs-full.sqfs"
BACKUP_IMG="$OUT/backup-alpine.img"
INITRAMFS="$BUILD/initramfs.cpio.xz"
MUSL_WORK="$OUT/musl"

export KBUILD_BUILD_USER=hy300 KBUILD_BUILD_HOST=build HY300_RK3566

kmake() {
	make -s -C "$KSRC" O="$1" ARCH=arm64 CROSS_COMPILE="$CROSS" -j"$JOBS" "${@:2}"
}

fail() {
	echo "FALHOU: $*" >&2
	exit 1
}

read_listed_hash() {
	awk -v name="$2" '$2 == name || $2 == "./" name { print $1 }' "$1"
}

require_hash() {
	local want got
	want="$(read_listed_hash "$2" "$3")"
	got="$(sha256sum "$1" | cut -c1-64)"
	[[ -n "$want" && "$want" == "$got" ]] || fail "$1 não confere com $2"
}

require_inputs() {
	echo ">> entradas"
	require_hash "$FACTORY/recovery.img" "$FACTORY/SHA256SUMS" recovery.img
	require_hash "$BOOT_REF" "$(dirname "$(dirname "$BOOT_REF")")/SHA256SUMS" particoes/boot.img
	mkdir -p "$BUILD" "$OUT"
	python3 -I "$REPO/tools/build_inputs.py" pubkey "$SSH_PUBKEY" >"$BUILD/authorized_keys" || exit 1
	echo "ok: chave pública $(awk '{ print $1, $3 }' "$BUILD/authorized_keys")"
}

build_kernel() {
	echo ">> kernel: $(git -C "$KSRC" rev-parse --abbrev-ref HEAD) $(git -C "$KSRC" rev-parse --short HEAD)"
	mkdir -p "$KOUT"
	kmake "$KOUT" "${CONFIGS[@]}" >/dev/null 2>&1
	kmake "$KOUT" Image modules "rockchip/$DTB_NAME"
	python3 -I "$REPO/tools/build_inputs.py" kconfig "$KOUT/.config" "$REPO/config/kernel-required.txt" || exit 1
	grep -qa 'HY300 Projector' "$IMAGE" || fail "Image sem o DT embutido do HY300"
	KREL="$(kmake "$KOUT" -s kernelrelease)"
	gzip -9 -n -c "$IMAGE" >"$IMAGE_GZ"
	echo "ok: $KREL, Image $(stat -c %s "$IMAGE") bytes, Image.gz $(stat -c %s "$IMAGE_GZ") bytes"
}

stage_modules() {
	local dest="$BUILD/modules/$KREL" path
	rm -rf "$BUILD/modules"
	mkdir -p "$dest/kernel"
	grep -v '^#' "$REPO/config/modules.txt" | grep . | while read -r path; do
		install -D -m 644 "$KOUT/$path" "$dest/kernel/$path"
		"${CROSS}strip" --strip-debug "$dest/kernel/$path"
	done
	grep -v '^#' "$REPO/config/modules.txt" | grep . | sed 's|^|kernel/|' >"$dest/modules.order"
	cp "$KOUT/modules.builtin" "$KOUT/modules.builtin.modinfo" "$dest/"
}

# Programas estáticos (musl, do lib-musl.sh do hy300-rk3566): o hy300-waitkey daqui e o
# reboot-recovery de lá (reboot(RESTART2, "recovery"), sem BCB).
build_static_tools() {
	echo ">> programas estáticos (musl)"
	local sysroot="$MUSL_WORK/sysroot"
	mkdir -p "$BUILD/bin"
	make -s -C "$KSRC" O="$MUSL_WORK/kheaders" ARCH=arm64 INSTALL_HDR_PATH="$sysroot" headers_install
	"$HY300_RK3566/kernel/reboot-recovery/build.sh" "$BUILD/bin/hy300-reboot-recovery" "$MUSL_WORK" >/dev/null
	REALGCC="${CROSS}gcc" "$sysroot/bin/musl-gcc" -static -Os -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
		-o "$BUILD/bin/hy300-waitkey" "$REPO/src/hy300-waitkey.c"
	REALGCC="${CROSS}gcc" "$sysroot/bin/musl-gcc" -static -Os -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
		-o "$BUILD/bin/hy300-watchdogd" "$REPO/src/hy300-watchdogd.c"
	"${CROSS}strip" "$BUILD/bin/hy300-waitkey" "$BUILD/bin/hy300-watchdogd"
}

build_hostkey() {
	local key="$OUT/ssh-host/ssh_host_ed25519_key"
	[[ -f "$key" ]] || { mkdir -p "$OUT/ssh-host"; ssh-keygen -q -t ed25519 -N '' -C hy300-recuperacao -f "$key"; }
	HOSTKEY="$key"
}

build_wifi() {
	echo ">> Wi-Fi: rede de casa, ponto de acesso e firmware"
	rm -rf "$BUILD/wifi"
	python3 -I "$REPO/tools/build_inputs.py" wifi --credentials "$WIFI_CREDENTIALS" --vendor-img "$VENDOR_IMG" \
		--ap-conf "$OUT/ap.conf" --out "$BUILD/wifi" || exit 1
}

fetch_alpine() {
	echo ">> Alpine $ALPINE_VERSION"
	python3 -I "$REPO/tools/alpine_fetch.py" bootstrap --version "$ALPINE_VERSION" --out "$BUILD/dl" | head -n 1
}

# $1: rootfs, $2: squashfs, $3: listas de pacotes (config/), $4: modo (núcleo ou completo).
build_one_rootfs() {
	local info
	info="alpine=$ALPINE_VERSION rootfs=$4 kernel=$(git -C "$KSRC" rev-parse --short HEAD) hy300-alpine=$(git -C "$REPO" rev-parse --short HEAD) data=$(date -u +%Y-%m-%d)"
	REPO="$REPO" ROOT="$1" SQUASHFS="$2" PACKAGE_LISTS="$3" APK_CACHE="$BUILD/apk-cache" \
		MINIROOTFS="$BUILD/dl/alpine-minirootfs-$ALPINE_VERSION-aarch64.tar.gz" APK_STATIC="$BUILD/dl/apk.static" \
		ALPINE_BRANCH="$ALPINE_BRANCH" KREL="$KREL" MODULES_DIR="$BUILD/modules" WIFI_DIR="$BUILD/wifi" \
		AUTHORIZED_KEY="$BUILD/authorized_keys" HOSTKEY="$HOSTKEY" EXTRA_BIN="$BUILD/bin" BUILD_INFO="$info" \
		unshare --map-auto --map-root-user bash "$REPO/tools/mkrootfs.sh"
	echo "ok: $(basename "$2") $(stat -c %s "$2") bytes"
}

build_rootfs() {
	echo ">> rootfs do núcleo (initramfs, modo de resgate) e completo (backup), em user namespace"
	build_one_rootfs "$BUILD/rootfs" "$SQUASHFS" "packages.txt" núcleo
	build_one_rootfs "$BUILD/rootfs-full" "$FULL_SQUASHFS" "packages.txt extras.txt desktop.txt" completo
}

# ext4 da partição backup, do tamanho exato dela: rootfs.sqfs, o .sha256 que o estágio 1
# confere e config/ (redes salvas). mke2fs -d no user namespace, para os arquivos serem de root.
build_backup_image() {
	echo ">> backup-alpine.img"
	local dir="$BUILD/backup-root"
	rm -rf "$dir" "$BACKUP_IMG"
	mkdir -p "$dir/config"
	cp "$FULL_SQUASHFS" "$dir/rootfs.sqfs"
	(cd "$dir" && sha256sum rootfs.sqfs >rootfs.sqfs.sha256)
	cp "$BUILD/rootfs-full/etc/hy300-build" "$dir/VERSAO"
	truncate -s "$BACKUP_SIZE" "$BACKUP_IMG"
	unshare --map-auto --map-root-user mke2fs -q -F -t ext4 -L hy300-alpine -m 0 -J size=4 -d "$dir" "$BACKUP_IMG"
	sha256sum "$BACKUP_IMG" | sed "s|$OUT/||" >"$BACKUP_IMG.sha256"
	echo "ok: backup-alpine.img ($(du -h --apparent-size "$BACKUP_IMG" | cut -f1), rootfs.sqfs $(stat -c %s "$FULL_SQUASHFS") bytes)"
}

build_initramfs() {
	echo ">> initramfs"
	gcc -O2 -o "$BUILD/gen_init_cpio" "$KSRC/usr/gen_init_cpio.c"
	cat >"$BUILD/cpio.list" <<-EOF
		dir /bin 755 0 0
		dir /dev 755 0 0
		dir /proc 755 0 0
		dir /sys 755 0 0
		dir /tmp 1777 0 0
		dir /mnt 755 0 0
		nod /dev/console 600 0 0 c 5 1
		nod /dev/kmsg 644 0 0 c 1 11
		file /init $REPO/initramfs/init 755 0 0
		file /bin/busybox $BUILD/rootfs/bin/busybox.static 755 0 0
		file /bin/hy300-reboot-recovery $BUILD/bin/hy300-reboot-recovery 755 0 0
		file /rootfs.sqfs $SQUASHFS 644 0 0
	EOF
	"$BUILD/gen_init_cpio" -t 0 "$BUILD/cpio.list" | xz --check=crc32 -9 -T1 >"$INITRAMFS"
	echo "ok: initramfs $(stat -c %s "$INITRAMFS") bytes"
}

build_image() {
	python3 -I "$REPO/tools/mkimage.py" --like "$1" -o "$2" --kernel "$3" --ramdisk "$INITRAMFS" --dtb "$DTB" \
		--append "hy300.slot=$4 $CMDLINE${5:+ $5}" --pad-to-like || fail "$(basename "$2") não cabe na partição $4"
}

build_images() {
	echo ">> imagens"
	build_image "$FACTORY/recovery.img" "$OUT/recovery-alpine.img" "$IMAGE_GZ" recovery
	build_image "$BOOT_REF" "$OUT/boot-alpine.img" "$IMAGE_GZ" boot "$BOOT_ONLY_CMDLINE"
	build_image "$FACTORY/recovery.img" "$OUT/recovery-alpine-image-crua.img" "$IMAGE" recovery
}

require_same() {
	cmp -s "$1" "$2" || fail "$3"
}

verify_image() {
	local img="$1" like="$2" kernel="$3" slot="$4" size="$5" check="$BUILD/check-$4"
	rm -rf "$check"
	python3 -I "$HY300_RK3566/tools/mkboot.py" unpack "$img" "$check" >/dev/null
	python3 -I "$HY300_RK3566/tools/mkboot.py" unpack "$like" "$check/like" >/dev/null
	python3 -I "$HY300_RK3566/tools/rk_resource.py" unpack "$check/second" "$check/res" >/dev/null
	[[ "$(stat -c %s "$img")" == "$size" ]] || fail "$img não tem o tamanho da partição ($size)"
	[[ "$(stat -c %s "$FACTORY/backup.img")" == "$BACKUP_SIZE" ]] || fail "backup.img de fábrica com tamanho inesperado"
	require_same "$check/kernel" "$kernel" "$img: kernel"
	require_same "$check/ramdisk" "$INITRAMFS" "$img: ramdisk"
	require_same "$check/dtb" "$DTB" "$img: seção dtb"
	require_same "$check/second" "$check/like/second" "$img: resource de fábrica"
	grep -qa 'snps,dwcmshc-sdhci' "$check/res/rk-kernel.dtb" || fail "$img: DT do resource sem o eMMC do U-Boot"
	grep -q "hy300.slot=$slot " "$check/header.json" || fail "$img: cmdline sem hy300.slot=$slot"
	[[ "$slot" == boot ]] || ! grep -q "hy300.crash_to_recovery" "$check/header.json" ||
		fail "$img: hy300.crash_to_recovery fora da imagem da boot (laço na recovery)"
	[[ "$slot" != boot ]] || grep -q "hy300.crash_to_recovery=1" "$check/header.json" ||
		fail "$img: imagem da boot sem hy300.crash_to_recovery=1"
	sha256sum "$img" | sed "s|$OUT/||" >"$img.sha256"
}

report_budget() {
	local used
	used=$(python3 -I -c "import sys; sys.path.insert(0, '$HY300_RK3566/tools'); import mkboot
img = mkboot.unpack(open('$OUT/boot-alpine.img', 'rb').read()); print(mkboot.build_section_offsets(img)[1])")
	echo "boot-alpine.img: $used bytes usados de $BOOT_SIZE (sobram $((BOOT_SIZE - used)))"
}

verify_images() {
	echo ">> conferência"
	verify_image "$OUT/recovery-alpine.img" "$FACTORY/recovery.img" "$IMAGE_GZ" recovery "$RECOVERY_SIZE"
	verify_image "$OUT/boot-alpine.img" "$BOOT_REF" "$IMAGE_GZ" boot "$BOOT_SIZE"
	verify_image "$OUT/recovery-alpine-image-crua.img" "$FACTORY/recovery.img" "$IMAGE" recovery "$RECOVERY_SIZE"
	cat "$OUT"/*.img.sha256
	report_budget
	echo "backup-alpine.img: rootfs.sqfs de $(stat -c %s "$FULL_SQUASHFS") bytes em $BACKUP_SIZE"
}

# known_hosts pronto para o PC: o IP fixo de casa e o do ponto de acesso.
write_known_hosts() {
	local address key
	address="$(sed -n 's/^WIFI_ADDRESS=//p' "$BUILD/wifi/etc/hy300-wifi.conf" | cut -d/ -f1)"
	key="$(cut -d' ' -f1,2 "$HOSTKEY.pub")"
	printf '%s %s\n' "$address" "$key" "192.168.50.1" "$key" >"$OUT/known_hosts"
}

run_smoke() {
	[[ "$SMOKE" == 1 ]] || { echo ">> smoke: pulado (SMOKE=$SMOKE)"; return; }
	echo ">> smoke (QEMU)"
	local qout="$KOUT-qemu"
	mkdir -p "$qout"
	kmake "$qout" "${CONFIGS[@]}" >/dev/null 2>&1
	"$KSRC/scripts/kconfig/merge_config.sh" -m -O "$qout" "$qout/.config" \
		"$HY300_RK3566/kernel/initramfs-test/qemu.config" "$REPO/tests/qemu.config" >/dev/null
	kmake "$qout" olddefconfig >/dev/null
	kmake "$qout" Image
	python3 -I "$REPO/tests/smoke_qemu.py" "$qout/arch/arm64/boot/Image" "$INITRAMFS" "$BUILD/qemu" \
		"$FACTORY/misc.img" "$SSH_PUBKEY" "$BACKUP_IMG"
}

main() {
	require_inputs
	build_kernel
	stage_modules
	build_static_tools
	build_hostkey
	build_wifi
	fetch_alpine
	build_rootfs
	build_backup_image
	build_initramfs
	build_images
	verify_images
	write_known_hosts
	run_smoke
}

main
