#!/usr/bin/env bash
# Grava uma imagem crua numa partição do HY300 pelo SSH da recuperação Alpine: manda comprimida
# com zstd e o hy300-flash do aparelho confere o SHA-256 lendo a partição de volta.
#
# Uso: scripts/hy300-flash-partition.sh IP PARTIÇÃO IMAGEM [--force]
#   --force: necessário para uboot, trust, misc e security.
# A super esparsa precisa virar crua antes (simg2img super.img super.raw).
# Variável: HY300_SSH (comando ssh, padrão "ssh -o BatchMode=yes").
set -euo pipefail
IP="$1"
PART="$2"
IMG="$3"
FORCE="${4:-}"
SSH=(${HY300_SSH:-ssh -o BatchMode=yes})

size="$(stat -c %s "$IMG")"
sha="$(sha256sum "$IMG" | cut -c1-64)"
echo ">> $IMG ($size bytes, $sha) -> $PART"
zstd -q -c -3 "$IMG" | "${SSH[@]}" "root@$IP" "zstd -q -d | hy300-flash $FORCE --size $size --sha256 $sha $PART -"
