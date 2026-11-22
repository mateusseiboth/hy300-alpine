#!/usr/bin/env bash
# Monta o rootfs do Alpine e o squashfs. Roda dentro de um user namespace
# (unshare --map-auto --map-root-user): o apk.static instala como "root" sem root de verdade, e
# os scripts dos pacotes (aarch64) rodam pelo binfmt do qemu-aarch64-static. Chamado pelo
# build.sh com as variáveis abaixo no ambiente; não roda sozinho.
#
# Entradas: REPO, ROOT, SQUASHFS, PACKAGE_LISTS (arquivos de config/ com os pacotes, separados
#           por espaço), MINIROOTFS, APK_STATIC, APK_CACHE, ALPINE_BRANCH, KREL,
#           MODULES_DIR (módulos já escolhidos), WIFI_DIR (rede/firmware), AUTHORIZED_KEY,
#           HOSTKEY, EXTRA_BIN (hy300-waitkey e hy300-reboot-recovery), BUILD_INFO.
set -euo pipefail

read_list() {
	grep -v '^#' "$1" | grep . || true
}

apk_root() {
	"$APK_STATIC" --root "$ROOT" --arch aarch64 --keys-dir "$ROOT/etc/apk/keys" --cache-dir "$APK_CACHE" \
		--no-interactive "$@"
}

install_packages() {
	rm -rf "$ROOT"
	mkdir -p "$ROOT" "$APK_CACHE"
	tar -xzf "$MINIROOTFS" -C "$ROOT"
	printf '%s\n' "https://dl-cdn.alpinelinux.org/alpine/$ALPINE_BRANCH/main" \
		"https://dl-cdn.alpinelinux.org/alpine/$ALPINE_BRANCH/community" >"$ROOT/etc/apk/repositories"
	local list packages=()
	for list in $PACKAGE_LISTS; do
		mapfile -t -O "${#packages[@]}" packages < <(read_list "$REPO/config/$list")
	done
	apk_root --update-cache add "${packages[@]}" >"$ROOT.apk.log"
	tail -n 1 "$ROOT.apk.log"
	# shellcheck disable=SC2046
	python3 -I "$REPO/tools/build_inputs.py" prune "$ROOT" $(read_list "$REPO/config/prune.txt")
}

install_overlay() {
	cp -a "$REPO/rootfs/." "$ROOT/"
	chown -R 0:0 "$ROOT/etc/inittab" "$ROOT/etc/ssh" "$ROOT/etc/hy300" "$ROOT/usr/lib/hy300" "$ROOT/usr/sbin"
	cp -a "$EXTRA_BIN/." "$ROOT/usr/sbin/"
	chown 0:0 "$ROOT"/usr/sbin/hy300-*
	cp -a "$MODULES_DIR/." "$ROOT/lib/modules/"
	chown -R 0:0 "$ROOT/lib/modules"
	depmod -b "$ROOT" "$KREL"
	cp -a "$WIFI_DIR/." "$ROOT/"
	chown -R 0:0 "$ROOT/etc/wpa_supplicant" "$ROOT/etc/hy300-wifi.conf" "$ROOT/etc/hy300-ap.conf" "$ROOT/lib/firmware"
}

install_ssh() {
	install -d -m 700 "$ROOT/root/.ssh"
	install -m 600 "$AUTHORIZED_KEY" "$ROOT/root/.ssh/authorized_keys"
	install -m 600 "$HOSTKEY" "$ROOT/etc/ssh/ssh_host_ed25519_key"
	install -m 644 "$HOSTKEY.pub" "$ROOT/etc/ssh/ssh_host_ed25519_key.pub"
	# Sem senha nenhuma: "*" não casa com senha e não conta como conta travada para o sshd.
	sed -i 's/^root:[^:]*:/root:*:/' "$ROOT/etc/shadow"
}

finish_rootfs() {
	echo "$BUILD_INFO" >"$ROOT/etc/hy300-build"
	echo hy300 >"$ROOT/etc/hostname"
	rm -rf "$ROOT/var/cache/apk"/* "$ROOT/etc/apk/cache"
	mkdir -p "$ROOT/var/empty"
}

build_squashfs() {
	rm -f "$SQUASHFS"
	mksquashfs "$ROOT" "$SQUASHFS" -comp xz -b 1M -Xdict-size 100% -noappend -no-xattrs -quiet -no-progress
}

install_packages
install_overlay
install_ssh
finish_rootfs
build_squashfs
