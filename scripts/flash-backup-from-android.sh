#!/usr/bin/env bash
# Grava a imagem do Alpine completo (backup-alpine.img) na partição backup a partir do Android
# de fábrica, conferindo o SHA-256 no aparelho antes de gravar (cópia em /data/local/tmp) e
# depois. Mesmo fluxo do scripts/flash-test-recovery.sh do hy300-rk3566.
#
# Uso: scripts/flash-backup-from-android.sh [imagem]
#   padrão: ~/hy300-work/alpine/backup-alpine.img
#
# Só grava se a backup estiver toda zerada (como veio de fábrica) ou tiver uma imagem que este
# script já gravou (registradas em ~/hy300-work/alpine/backup-gravadas.txt, HY300_BACKUP_KNOWN).
# Depois que o Alpine salva uma rede, o hash muda e a regravação é recusada: para atualizar o
# Alpine com ele rodando, use o hy300-update dele (README). A partição de volta ao estado de
# fábrica: dd if=/dev/zero of=/dev/block/by-name/backup.
set -euo pipefail
IMG="${1:-$HOME/hy300-work/alpine/backup-alpine.img}"
KNOWN="${HY300_BACKUP_KNOWN:-$HOME/hy300-work/alpine/backup-gravadas.txt}"
PART=/dev/block/by-name/backup
TMP=/data/local/tmp/hy300-backup.img

fail() {
	echo "$1"
	exit 1
}

device_hash() {
	adb shell "sha256sum $PART" | cut -c1-64
}

build_zero_hash() {
	head -c "$1" /dev/zero | sha256sum | cut -c1-64
}

is_known() {
	grep -qx "$1" "$KNOWN" 2>/dev/null
}

require_writable() {
	local current="$1" size="$2"
	[[ "$current" == "$(build_zero_hash "$size")" ]] && { echo ">> backup zerada (estado de fábrica)"; return; }
	is_known "$current" && { echo ">> backup com uma imagem nossa ($current)"; return; }
	fail "a backup não está zerada nem tem uma imagem registrada ($current); abortando"
}

main() {
	[[ -f "$IMG" ]] || fail "$IMG não existe (rode o build.sh)"
	adb root >/dev/null
	sleep 3
	adb wait-for-device
	local part_size want current pushed written
	part_size="$(adb shell "blockdev --getsize64 $PART" | tr -d '\r')"
	(($(stat -c %s "$IMG") <= part_size)) || fail "imagem maior que a partição backup ($part_size bytes)"
	current="$(device_hash)"
	require_writable "$current" "$part_size"
	want="$(sha256sum "$IMG" | cut -c1-64)"
	echo ">> enviando $(basename "$IMG")"
	adb push "$IMG" "$TMP" >/dev/null
	pushed="$(adb shell "sha256sum $TMP" | cut -c1-64)"
	[[ "$pushed" == "$want" ]] || { adb shell "rm -f $TMP"; fail "FALHOU: a cópia chegou com hash $pushed"; }
	echo ">> gravando na backup"
	adb shell "dd if=$TMP of=$PART bs=4M conv=notrunc 2>/dev/null && sync; rm -f $TMP"
	written="$(adb shell "head -c $(stat -c %s "$IMG") $PART | sha256sum" | cut -c1-64)"
	[[ "$written" == "$want" ]] || fail "FALHOU: hash gravado $written != $want"
	mkdir -p "$(dirname "$KNOWN")"
	device_hash >>"$KNOWN"
	echo "ok: backup = $(basename "$IMG") ($want)"
}

main
