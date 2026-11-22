# Rede da recuperação: Wi-Fi AIC8800D80 com IP fixo e Ethernet USB com DHCP. Shell POSIX
# (tests/test_network.py). Adaptado do modo Wi-Fi do initramfs de teste do hy300-rk3566.
#
# O build põe em /etc/wpa_supplicant/wpa_supplicant.conf a rede (SSID em hexadecimal e a PSK já
# derivada) e em /etc/hy300-wifi.conf o IP fixo, o gateway e o DNS, validados por
# tools/wifi_payload.py do hy300-rk3566. O firmware vem do vendor.img de fábrica.
# shellcheck shell=sh

: "${HY300_SYSFS_NET:=/sys/class/net}"
WIFI_FIRMWARE_DIR=/lib/firmware/aic8800
WIFI_WPA_CONF=/etc/wpa_supplicant/wpa_supplicant.conf
WIFI_NET_CONF=/etc/hy300-wifi.conf
WIFI_WPA_CTRL=/var/run/wpa_supplicant
ARPHRD_ETHER=1
# O Android de fábrica roda o SDIO do AIC8800D80 a 50 MHz; o driver pediria 150 MHz, e no
# kernel ACK o envio do firmware estoura o tempo assim (parâmetro do commit 0408d7166c75 do
# hy300-6.1).
WIFI_SDIO_CLOCK=50000000

# Religar o chip sem tirar da tomada (lógica do initramfs de teste do hy300-rk3566, commit
# 36a14d5): o unbind do host SDIO faz o mmc-pwrseq-simple baixar o WL_REG_ON (GPIO2_B1,
# gpio-73) e cortar o clock de 32 kHz; o bind religa e o núcleo MMC enumera o cartão de novo.
# Um AIC8800 travado sobrevive a reboot quente: sem isto, só voltaria com corte de energia.
: "${WIFI_SDIO_HOST_ADDR:=fe2c0000}"
: "${WIFI_SDIO_VENDOR:=0xc8a1}"
: "${WIFI_PLATFORM_DEVICES:=/sys/bus/platform/devices}"
: "${WIFI_SDIO_DRIVER:=/sys/bus/platform/drivers/dwmmc_rockchip}"
: "${WIFI_SDIO_DEVICES:=/sys/bus/sdio/devices}"
: "${WIFI_POWER_OFF_SECONDS:=2}"
: "${WIFI_CARD_WAIT:=10}"

# O nome do nó muda entre as árvores (mmc@fe2c0000 no BSP, dwmmc@fe2c0000 no ACK).
find_sdio_host() {
	for dev in "$WIFI_PLATFORM_DEVICES/$WIFI_SDIO_HOST_ADDR".*; do
		[ -e "$dev" ] || continue
		basename "$dev"
		return 0
	done
	return 1
}

has_wifi_card() {
	for vendor in "$WIFI_SDIO_DEVICES"/*/vendor; do
		[ "$(cat "$vendor" 2>/dev/null)" = "$WIFI_SDIO_VENDOR" ] && return 0
	done
	return 1
}

wait_for_wifi_card() {
	remaining=$1
	while :; do
		has_wifi_card && return 0
		[ "$remaining" -gt 0 ] || return 1
		remaining=$((remaining - 1))
		sleep 1
	done
}

unload_wifi_modules() {
	rmmod aic8800_fdrv 2>/dev/null
	rmmod aic8800_bsp 2>/dev/null
	return 0
}

power_cycle_wifi_chip() {
	unload_wifi_modules
	host=$(find_sdio_host) || { echo "host SDIO $WIFI_SDIO_HOST_ADDR não encontrado"; return 1; }
	echo "$host" 2>/dev/null >"$WIFI_SDIO_DRIVER/unbind" || { echo "unbind de $host falhou"; return 1; }
	sleep "$WIFI_POWER_OFF_SECONDS"
	echo "$host" 2>/dev/null >"$WIFI_SDIO_DRIVER/bind" || { echo "bind de $host falhou"; return 1; }
	wait_for_wifi_card "$WIFI_CARD_WAIT" || { echo "o chip Wi-Fi não voltou ao barramento SDIO em $WIFI_CARD_WAIT s"; return 1; }
}

load_wifi_modules() {
	modprobe aic8800_bsp "aic_fw_path=$1" "sdio_clock=$WIFI_SDIO_CLOCK" || { echo "modprobe aic8800_bsp falhou"; return 1; }
	modprobe aic8800_fdrv || { echo "modprobe aic8800_fdrv falhou"; return 1; }
}

is_wireless_iface() {
	[ -d "$HY300_SYSFS_NET/$1/wireless" ] || [ -e "$HY300_SYSFS_NET/$1/phy80211" ]
}

find_wireless_iface() {
	for dir in "$HY300_SYSFS_NET"/*; do
		[ -d "$dir" ] || continue
		is_wireless_iface "$(basename "$dir")" || continue
		basename "$dir"
		return 0
	done
	return 1
}

wait_for_wireless_iface() {
	remaining=$1
	while :; do
		find_wireless_iface && return 0
		[ "$remaining" -gt 0 ] || return 1
		remaining=$((remaining - 1))
		sleep 1
	done
}

# Interfaces Ethernet de verdade: tipo ARPHRD_ETHER e sem extensões sem fio (lo, sit e afins
# têm outro tipo).
find_ethernet_ifaces() {
	for dir in "$HY300_SYSFS_NET"/*; do
		name=$(basename "$dir")
		[ "$(cat "$dir/type" 2>/dev/null)" = "$ARPHRD_ETHER" ] || continue
		is_wireless_iface "$name" && continue
		echo "$name"
	done
}

start_wpa_supplicant() {
	wpa_supplicant -B -s -D nl80211 -i "$1" -c "$2"
}

read_wpa_state() {
	wpa_cli -p "$WIFI_WPA_CTRL" -i "$1" status 2>/dev/null | sed -n 's/^wpa_state=//p'
}

# O arquivo de rede é gerado e validado no build: só atribuições.
configure_static_ip() {
	# shellcheck source=/dev/null
	. "$2"
	ip link set lo up
	ip addr replace "$WIFI_ADDRESS" dev "$1" || return 1
	ip link set "$1" up || return 1
	ip route replace default via "$WIFI_GATEWAY" dev "$1" || return 1
	echo "nameserver $WIFI_DNS" >"${3:-/etc/resolv.conf}"
}

# ARP não solicitado: o IP pode ter sido do Android, com outro MAC, no cache do roteador.
announce_ip() {
	arping -U -c 2 -I "$1" "$2" >/dev/null 2>&1
}

read_iface_ip() {
	ip -4 -o addr show dev "$1" 2>/dev/null | awk '{ split($4, a, "/"); print a[1]; exit }'
}

is_dhcp_running() {
	pid=$(cat "$HY300_RUN/udhcpc.$1.pid" 2>/dev/null) || return 1
	[ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_dhcp() {
	mkdir -p "$HY300_RUN"
	ip link set "$1" up
	udhcpc -b -S -i "$1" -p "$HY300_RUN/udhcpc.$1.pid" -x hostname:hy300
}

stop_dhcp() {
	pid=$(cat "$HY300_RUN/udhcpc.$1.pid" 2>/dev/null) || return 0
	kill "$pid" 2>/dev/null
	rm -f "$HY300_RUN/udhcpc.$1.pid"
}

# Estado do Wi-Fi para a tela e o hy300-wifi: modo (station ou ap) e uma linha de texto.
write_wifi_state() {
	mkdir -p "$HY300_RUN"
	echo "$1" >"$HY300_RUN/wifi-state"
}

write_wifi_mode() {
	mkdir -p "$HY300_RUN"
	echo "$1" >"$HY300_RUN/wifi-mode"
}

read_wpa_field() {
	wpa_cli -p "$WIFI_WPA_CTRL" -i "$1" status 2>/dev/null | sed -n "s/^$2=//p"
}

# A rede de casa leva id_str="casa" no wpa_supplicant.conf gerado no build (tools/wifi_conf.py).
is_home_network() {
	[ "$(read_wpa_field "$1" id_str)" = casa ]
}

# Rede de casa: IP fixo do credenciais.conf. Qualquer outra: DHCP.
configure_wifi_address() {
	stop_dhcp "$1"
	ip addr flush dev "$1" 2>/dev/null
	is_home_network "$1" || { start_dhcp "$1"; return; }
	configure_static_ip "$1" "$WIFI_NET_CONF" "$2" || return 1
	. "$WIFI_NET_CONF"
	announce_ip "$1" "${WIFI_ADDRESS%/*}"
}

# Espera a associação por até $2 segundos e configura o endereço. O wpa_supplicant já precisa
# estar rodando.
run_station_attempt() {
	remaining=$2
	while :; do
		state=$(read_wpa_field "$1" wpa_state)
		[ "$state" = COMPLETED ] && break
		write_wifi_state "procurando rede (${state:-sem resposta do wpa_supplicant})"
		[ "$remaining" -gt 0 ] || return 1
		remaining=$((remaining - 1))
		sleep 1
	done
	ssid=$(read_wpa_field "$1" ssid)
	configure_wifi_address "$1" "${3:-/etc/resolv.conf}" || { write_wifi_state "FALHOU: endereço em $ssid"; return 1; }
	write_wifi_mode station
	write_wifi_state "conectado em $ssid"
}

# Ponto de acesso próprio (fallback quando nenhuma rede conhecida está ao alcance).
WIFI_AP_CONF=/etc/hy300-ap.conf
WIFI_AP_ADDRESS=192.168.50.1
WIFI_AP_PREFIX=24
WIFI_AP_CHANNEL=6

build_hostapd_conf() {
	printf '%s\n' "interface=$1" "driver=nl80211" "ctrl_interface=/var/run/hostapd" "ssid=$2" \
		"hw_mode=g" "channel=$WIFI_AP_CHANNEL" "auth_algs=1" "wpa=2" "wpa_key_mgmt=WPA-PSK" \
		"rsn_pairwise=CCMP" "wpa_passphrase=$3"
}

build_udhcpd_conf() {
	printf '%s\n' "interface $1" "start 192.168.50.10" "end 192.168.50.50" "max_leases 40" \
		"option subnet 255.255.255.0" "lease_file $HY300_RUN/udhcpd.leases" "pidfile $HY300_RUN/udhcpd.pid"
}

leave_ap_mode() {
	pkill -x hostapd 2>/dev/null
	pkill -x udhcpd 2>/dev/null
	ip addr flush dev "$1" 2>/dev/null
	return 0
}

stop_station() {
	pkill -x wpa_supplicant 2>/dev/null
	stop_dhcp "$1"
	ip addr flush dev "$1" 2>/dev/null
	return 0
}

enter_ap_mode() {
	. "$WIFI_AP_CONF"
	stop_station "$1"
	ip addr add "$WIFI_AP_ADDRESS/$WIFI_AP_PREFIX" dev "$1" || return 1
	ip link set "$1" up
	build_hostapd_conf "$1" "$AP_SSID" "$AP_PASSPHRASE" >"$HY300_RUN/hostapd.conf"
	hostapd -B -P "$HY300_RUN/hostapd.pid" "$HY300_RUN/hostapd.conf" ||
		{ write_wifi_state "FALHOU: ponto de acesso não abriu"; return 1; }
	build_udhcpd_conf "$1" >"$HY300_RUN/udhcpd.conf"
	: >"$HY300_RUN/udhcpd.leases"
	udhcpd "$HY300_RUN/udhcpd.conf"
	write_wifi_mode ap
	write_wifi_state "ponto de acesso $AP_SSID senha $AP_PASSPHRASE"
}

build_ssid_hex() {
	printf '%s' "$1" | od -An -tx1 | tr -d ' \n'
}

# Acrescenta uma rede ao wpa_supplicant.conf: com senha (WPA-PSK, PSK já derivada, sem a senha
# em claro) ou aberta (senha vazia). Redes adicionadas usam DHCP e têm prioridade sobre a de
# casa (priority=10): quem escolheu a rede pediu essa.
WIFI_ADDED_PRIORITY=20

add_wifi_network() {
	[ -n "$2" ] || { echo "informe o nome da rede"; return 1; }
	[ -n "$3" ] || { printf 'network={\n\tssid=%s\n\tkey_mgmt=NONE\n\tpriority=%s\n}\n' "$(build_ssid_hex "$2")" "$WIFI_ADDED_PRIORITY" >>"$1"; return; }
	length=${#3}
	[ "$length" -ge 8 ] && [ "$length" -le 63 ] || { echo "a senha do Wi-Fi tem de 8 a 63 caracteres"; return 1; }
	wpa_block=$(wpa_passphrase "$2" "$3") || { echo "wpa_passphrase falhou"; return 1; }
	echo "$wpa_block" | grep -v '^[[:space:]]*#psk=' |
		awk -v p="$WIFI_ADDED_PRIORITY" '/^}$/ { print "\tpriority=" p } { print }' >>"$1"
}

# Entrada: o scan_results do wpa_cli (bssid, frequência, sinal, flags e SSID separados por tab).
# Saída: "  -45 dBm  Nome", uma linha por SSID (o ponto de acesso mais forte), sem redes ocultas.
build_scan_list() {
	awk -F '\t' 'NF >= 5 && $3 ~ /^-?[0-9]+$/ && $5 != "" { printf "%d\t%s\n", $3, $5 }' |
		sort -t "$(printf '\t')" -k1,1 -n -r |
		awk -F '\t' '!seen[$2]++ { printf "%6d dBm  %s\n", $1, $2 }'
}
