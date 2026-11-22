# Tela de status da recuperação (fbcon, fonte 16x32: 64x18 caracteres). Shell POSIX
# (tests/test_screen.py).
# shellcheck shell=sh

# Primeiro IP utilizável das linhas "<iface> <ip|-> [estado]": Wi-Fi antes do cabo.
read_first_ip() {
	for line in "$@"; do
		ip=$(echo "$line" | awk '{ print $2 }')
		case "$ip" in
		'' | -) continue ;;
		esac
		echo "$ip"
		return 0
	done
	return 1
}

build_iface_line() {
	[ -n "$2" ] || { echo "$1: não encontrado"; return; }
	set -- "$1" $2
	label=$1
	iface=$2
	ip=$3
	shift 3
	[ "$ip" = - ] && ip="sem endereço"
	[ $# -gt 0 ] && { echo "$label $iface: $ip ($*)"; return; }
	echo "$label $iface: $ip"
}

# Arte "6BOT" no topo do menu (figlet, fonte standard).
build_logo() {
	cat <<'LOGO'
     __    ____     ___    _____
    / /_  | __ )   / _ \  |_   _|
   | '_ \ |  _ \  | | | |   | |
   | (_) || |_) | | |_| |   | |
    \___/ |____/   \___/    |_|
LOGO
}

build_ap_lines() {
	echo "  Conecte o celular ou o PC na rede $1"
	echo "  senha: $2"
}

build_access_lines() {
	ip=$(read_first_ip "$1" "$2") && { echo "  No PC: ssh root@$ip"; return; }
	echo "  Sem rede: escolha uma rede (3) ou ligue um cabo USB."
}

# Argumentos: versão do Alpine, partição do Alpine, partição do Android, linha do Wi-Fi
# ("wlan0 <ip|-> <estado>"), linha do cabo ("eth0 <ip|->" ou vazio), minutos no ar,
# temperatura do SoC (°C), RAM livre (MB), no modo ponto de acesso "<ssid> <senha>" e, no
# modo de resgate, a linha que explica.
build_status_text() {
	echo "  Alpine $1 na partição $2. Android na $3."
	[ -n "${10:-}" ] && echo "  ${10}"
	echo "  $(build_iface_line Wi-Fi "$4")"
	[ -n "$5" ] && echo "  $(build_iface_line Cabo "$5")"
	[ -n "${9:-}" ] && build_ap_lines $9
	build_access_lines "$4" "$5"
	echo "  No ar há $6 min. SoC a $7 °C. RAM livre: $8 MB."
}

# Tela do menu: arte, status e opções (64x18 com a fonte 16x32). Precisa do menu.sh.
build_main_screen() {
	build_logo
	echo
	build_status_text "$@"
	echo
	build_menu_lines
}
