# Configuração persistente na partição backup. Shell POSIX (tests/test_persist.py).
#
# A backup é um ext4 (rótulo hy300-alpine) com o rootfs.sqfs do Alpine completo e o diretório
# config/. O estágio 1 a monta só-leitura e o init a deixa em /media/backup. Para salvar,
# remonta rw só pelo tempo de gravar e voltar a só-leitura: um corte de energia fora desse
# instante não tem o que estragar, e dentro dele o journal do ext4 cuida.
# shellcheck shell=sh

: "${HY300_BACKUP:=/media/backup}"
PERSIST_WIFI=redes.conf

is_persist_available() {
	mountpoint -q "$HY300_BACKUP" && [ -d "$HY300_BACKUP/config" ]
}

# Acrescenta o arquivo $1 ao config/$2 da backup.
append_persistent() {
	mount -o remount,rw "$HY300_BACKUP" || return 1
	cat "$1" >>"$HY300_BACKUP/config/$2"
	result=$?
	sync
	mount -o remount,ro "$HY300_BACKUP"
	return "$result"
}

# Bloco network={...} de uma rede acrescentada: salvo na backup para os próximos boots.
save_wifi_block() {
	is_persist_available || { echo "sem a partição backup: a rede fica só na RAM até o próximo boot"; return 1; }
	append_persistent "$1" "$PERSIST_WIFI" || { echo "falha ao gravar na partição backup"; return 1; }
	echo "rede salva na partição backup"
}

# No boot: as redes salvas entram no wpa_supplicant.conf do build (a de casa vem do build).
restore_wifi_networks() {
	[ -f "$HY300_BACKUP/config/$PERSIST_WIFI" ] || return 0
	cat "$HY300_BACKUP/config/$PERSIST_WIFI" >>"$1"
}
