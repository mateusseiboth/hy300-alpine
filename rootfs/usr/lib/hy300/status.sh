# Coleta do estado para a tela e o hy300-status (usa common, network, screen, autoboot e menu).
# shellcheck shell=sh

read_wifi_line() {
	iface=$(cat "$HY300_RUN/wifi-iface" 2>/dev/null || echo wlan0)
	ip=$(read_iface_ip "$iface")
	echo "$iface ${ip:--} $(cat "$HY300_RUN/wifi-state" 2>/dev/null)"
}

read_ethernet_line() {
	for iface in $(find_ethernet_ifaces); do
		ip=$(read_iface_ip "$iface")
		echo "$iface ${ip:--}"
		return
	done
}

read_ap_line() {
	[ "$(cat "$HY300_RUN/wifi-mode" 2>/dev/null)" = ap ] || return 0
	. "$WIFI_AP_CONF"
	echo "$AP_SSID $AP_PASSPHRASE"
}

read_temperature() {
	millis=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
	echo $((millis / 1000))
}

read_mem_available() {
	awk '/^MemAvailable:/ { print int($2 / 1024) }' /proc/meminfo
}

# Só no modo de resgate (o estágio 1 escreve o modo em /etc/hy300-mode).
read_mode_line() {
	mode=$(cat /etc/hy300-mode 2>/dev/null)
	case "$mode" in
	resgate:*) echo "MODO DE RESGATE:${mode#resgate:}" ;;
	esac
}

collect_status() {
	build_main_screen "$(cat /etc/alpine-release)" "$(read_slot)" "$(read_android_slot)" "$(read_wifi_line)" \
		"$(read_ethernet_line)" "$(($(read_uptime) / 60))" "$(read_temperature)" "$(read_mem_available)" "$(read_ap_line)" \
		"$(read_mode_line)"
}
