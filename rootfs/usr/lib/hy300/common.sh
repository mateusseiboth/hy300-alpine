# Funções comuns da recuperação do HY300. Shell POSIX: roda no busybox do Alpine e no /bin/sh
# do host (tests/). Os caminhos do sistema vêm de variáveis para os testes trocarem.
# shellcheck shell=sh

: "${HY300_LIB:=/usr/lib/hy300}"
: "${HY300_RUN:=/run/hy300}"
: "${HY300_CMDLINE:=/proc/cmdline}"
: "${HY300_TTY:=/dev/tty1}"
: "${KMSG:=/dev/kmsg}"

# Registro no log do kernel (vai para o pstore enquanto o nível do console deixar).
log_kmsg() {
	echo "<5>hy300: [$1] $2" >>"$KMSG" 2>/dev/null
	return 0
}

read_uptime() {
	seconds=$(cut -d. -f1 /proc/uptime 2>/dev/null)
	echo "${seconds:-0}"
}

# Valor de "chave=valor" na cmdline (o último vence); o padrão se faltar.
read_cmdline_value() {
	value=$(awk -v key="$1=" '{ for (i = 1; i <= NF; i++) if (index($i, key) == 1) v = substr($i, length(key) + 1) } END { print v }' "$HY300_CMDLINE" 2>/dev/null)
	echo "${value:-$2}"
}

read_cmdline_number() {
	value=$(read_cmdline_value "$1" "")
	case "$value" in
	'' | *[!0-9]*) echo "$2" ;;
	*) echo "$value" ;;
	esac
}

# Partição de onde o U-Boot subiu esta imagem: o build grava hy300.slot=boot ou
# hy300.slot=recovery na cmdline de cada variante.
read_slot() {
	case "$(read_cmdline_value hy300.slot "")" in
	boot) echo boot ;;
	recovery) echo recovery ;;
	*) echo desconhecido ;;
	esac
}

# Texto inteiro numa tela limpa do console (fbcon). Falha de escrita não derruba ninguém.
show_screen() {
	printf '\033[2J\033[H\033[?25l%s\n' "$1" >"$HY300_TTY" 2>/dev/null
	return 0
}
