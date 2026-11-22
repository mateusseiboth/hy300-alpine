# Menu local no tty1, pelo teclado USB (receptor 2.4G). Shell POSIX (tests/test_menu.py).
#
# Uma tecla numérica por vez, lida do próprio terminal: não depende de mapa de teclas nem do
# controle IR. A escolha de rede numera as redes do scan (até 9, uma tecla).
# shellcheck shell=sh

MENU_MAX_NETWORKS=9

read_menu_action() {
	case "$1" in
	2) echo android ;;
	3) echo rede ;;
	4) echo shell ;;
	5) echo grafico ;;
	*) echo atualizar ;;
	esac
}

build_menu_lines() {
	echo "  1 Atualizar  2 Iniciar o Android  3 Escolher rede  4 Shell"
	echo "  5 Ambiente gráfico"
}

# Entrada: linhas do "hy300-wifi scan" ("  -40 dBm  Nome da rede"), da mais forte para a mais
# fraca. Saída: "  1  Nome (-40 dBm)".
build_network_list() {
	head -n "$MENU_MAX_NETWORKS" | awk '{ signal = $1; sub(/^[ \t]*[^ \t]+[ \t]+dBm[ \t]+/, ""); printf "  %d  %s (%s dBm)\n", NR, $0, signal }'
}

read_network_by_number() {
	name=$(head -n "$MENU_MAX_NETWORKS" | sed -n "${1}p" | sed 's/^[ \t]*[^ \t]*[ \t]*dBm[ \t]*//')
	[ -n "$name" ] || return 1
	echo "$name"
}
