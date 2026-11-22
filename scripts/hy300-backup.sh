#!/usr/bin/env bash
# Backup de partições do HY300 para o PC, pelo SSH da recuperação Alpine. Comprime com zstd no
# caminho e confere o SHA-256 dos dois lados.
#
# Uso: scripts/hy300-backup.sh IP DESTINO PARTIÇÃO...
#      scripts/hy300-backup.sh IP DESTINO --all     (todas menos userdata)
# Saída: DESTINO/<partição>.img e DESTINO/SHA256SUMS (acrescenta).
# Variável: HY300_SSH (comando ssh, padrão "ssh -o BatchMode=yes").
set -euo pipefail
IP="$1"
DEST="$2"
shift 2
SSH=(${HY300_SSH:-ssh -o BatchMode=yes})

remote() {
	"${SSH[@]}" "root@$IP" "$@"
}

list_all() {
	remote hy300-partitions | awk '$1 != "userdata" { print $1 }'
}

backup_one() {
	local part="$1" want got
	want="$(remote "sha256sum /dev/block/by-name/$part" | cut -c1-64)"
	[[ ${#want} == 64 ]] || { echo "FALHOU: $part não existe no aparelho"; return 1; }
	echo ">> $part"
	remote "zstd -q -c -3 </dev/block/by-name/$part" | zstd -q -d >"$DEST/$part.img"
	got="$(sha256sum "$DEST/$part.img" | cut -c1-64)"
	[[ "$got" == "$want" ]] || { echo "FALHOU: $part chegou com $got (no aparelho $want)"; return 1; }
	echo "$got  $part.img" >>"$DEST/SHA256SUMS"
	echo "ok: $part ($(stat -c %s "$DEST/$part.img") bytes)"
}

main() {
	mkdir -p "$DEST"
	[[ "${1:-}" == --all ]] && set -- $(list_all)
	(($# > 0)) || { sed -n '2,9s/^# \{0,1\}//p' "$0"; exit 2; }
	for part in "$@"; do
		backup_one "$part"
	done
}

main "$@"
