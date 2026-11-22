"""Rede da recuperação (rootfs/usr/lib/hy300/network.sh): Wi-Fi AIC8800 com IP fixo e
adaptadores Ethernet USB com DHCP.

Os comandos que mexem no sistema (modprobe, ip, wpa_supplicant, wpa_cli, udhcpc, arping) são
falsos e gravam os argumentos.

Rodar: python3 -I -m unittest discover -s tests
"""
import os

from shelltest import ShellMixin, make_suite

NET_CONF = "WIFI_ADDRESS=192.0.2.10/24\nWIFI_GATEWAY=192.0.2.1\nWIFI_DNS=192.0.2.53\n"


class NetworkMixin(ShellMixin):
    libs = ("common.sh", "network.sh")

    def setUp(self):
        super().setUp()
        for name in ("modprobe", "wpa_supplicant", "udhcpc", "arping"):
            self.fake(name)
        self.fake("ip", 'ip\\ -4\\ -o\\ addr\\ show\\ dev\\ wlan0) echo "3: wlan0    inet 192.0.2.10/24 scope global wlan0" ;;')
        self.fake("wpa_cli", 'wpa_cli*status) printf "bssid=x\\nwpa_state=COMPLETED\\n" ;;')

    def add_iface(self, name, kind="1", wireless=False):
        self.write(f"net/{name}/type", kind + "\n")
        if wireless:
            os.makedirs(self.path(f"net/{name}/wireless"))

    def env(self):
        return {"HY300_SYSFS_NET": self.path("net")}

    def test_load_wifi_modules_passes_firmware_path(self):
        r = self.sh("load_wifi_modules /lib/firmware/aic8800")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fake_log(), ["modprobe aic8800_bsp aic_fw_path=/lib/firmware/aic8800 sdio_clock=50000000",
                                           "modprobe aic8800_fdrv"])

    def test_load_wifi_modules_reports_failure(self):
        self.fake("modprobe", 'modprobe\\ aic8800_fdrv*) exit 1 ;;')
        r = self.sh("load_wifi_modules /fw")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("aic8800_fdrv", r.stdout)

    def test_find_wireless_and_ethernet_ifaces(self):
        self.add_iface("lo", "772")
        self.add_iface("wlan0", wireless=True)
        self.add_iface("eth0")
        self.add_iface("usb0")
        self.add_iface("sit0", "776")
        r = self.sh("find_wireless_iface; echo ---; find_ethernet_ifaces", env=self.env())
        self.assertEqual(r.stdout.split(), ["wlan0", "---", "eth0", "usb0"])

    def test_start_wpa_supplicant_logs_to_syslog(self):
        self.sh("start_wpa_supplicant wlan0 /etc/wpa_supplicant/wpa_supplicant.conf")
        self.assertEqual(self.fake_log(), ["wpa_supplicant -B -s -D nl80211 -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf"])

    def test_configure_static_ip(self):
        conf = self.write("hy300-wifi.conf", NET_CONF)
        resolv = self.path("resolv.conf")
        r = self.sh(f'configure_static_ip wlan0 "{conf}" "{resolv}"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fake_log(), ["ip link set lo up", "ip addr replace 192.0.2.10/24 dev wlan0",
                                           "ip link set wlan0 up", "ip route replace default via 192.0.2.1 dev wlan0"])
        self.assertEqual(open(resolv).read(), "nameserver 192.0.2.53\n")

    def test_read_wpa_state_and_iface_ip(self):
        r = self.sh("read_wpa_state wlan0; read_iface_ip wlan0")
        self.assertEqual(r.stdout.split(), ["COMPLETED", "192.0.2.10"])

    def test_start_dhcp_once_per_iface(self):
        r = self.sh("start_dhcp eth0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("udhcpc -b -S -i eth0 -p " + self.path("run/udhcpc.eth0.pid") + " -x hostname:hy300", self.fake_log())

    def status(self, state="COMPLETED", id_str="casa", ssid="Casa"):
        body = f"bssid=x\\nssid={ssid}\\nid_str={id_str}\\nwpa_state={state}\\n"
        self.fake("wpa_cli", f'wpa_cli*status) printf "{body}" ;;')

    def test_station_at_home_uses_static_ip(self):
        conf = self.write("hy300-wifi.conf", NET_CONF)
        self.status()
        r = self.sh(f'WIFI_NET_CONF="{conf}"; run_station_attempt wlan0 3 "{self.path("resolv")}"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ip addr replace 192.0.2.10/24 dev wlan0", self.fake_log())
        self.assertFalse(any(line.startswith("udhcpc") for line in self.fake_log()))
        self.assertIn("conectado em Casa", open(self.path("run/wifi-state")).read())

    def test_station_elsewhere_uses_dhcp(self):
        self.status(id_str="", ssid="Hotel")
        r = self.sh(f'run_station_attempt wlan0 3 "{self.path("resolv")}"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(line.startswith("udhcpc -b -S -i wlan0") for line in self.fake_log()))
        self.assertFalse(any("ip addr replace" in line for line in self.fake_log()))
        self.assertIn("conectado em Hotel", open(self.path("run/wifi-state")).read())

    def test_station_gives_up_after_wait(self):
        self.status(state="SCANNING")
        r = self.sh(f'run_station_attempt wlan0 1 "{self.path("resolv")}"')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SCANNING", open(self.path("run/wifi-state")).read())

    def test_hostapd_conf(self):
        r = self.sh("build_hostapd_conf wlan0 HY300-6bot-recovery senha-secreta1")
        conf = r.stdout
        for line in ("interface=wlan0", "driver=nl80211", "ssid=HY300-6bot-recovery", "hw_mode=g",
                     "wpa=2", "wpa_key_mgmt=WPA-PSK", "rsn_pairwise=CCMP", "wpa_passphrase=senha-secreta1"):
            self.assertIn(line + "\n", conf)

    def test_udhcpd_conf_serves_ap_subnet(self):
        conf = self.sh("build_udhcpd_conf wlan0").stdout
        self.assertIn("interface wlan0\n", conf)
        self.assertIn("start 192.168.50.10\n", conf)
        self.assertIn("end 192.168.50.50\n", conf)
        self.assertIn("option subnet 255.255.255.0\n", conf)

    def test_enter_ap_mode(self):
        ap = self.write("hy300-ap.conf", "AP_SSID=HY300-6bot-recovery\nAP_PASSPHRASE=abcdefgh1234\n")
        self.fake("hostapd")
        self.fake("udhcpd")
        self.fake("pkill")
        r = self.sh(f'WIFI_AP_CONF="{ap}"; enter_ap_mode wlan0')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.fake_log()
        self.assertIn("ip addr add 192.168.50.1/24 dev wlan0", log)
        self.assertTrue(any(line.startswith("hostapd -B") for line in log), log)
        self.assertTrue(any(line.startswith("udhcpd") for line in log), log)
        state = open(self.path("run/wifi-state")).read()
        self.assertIn("HY300-6bot-recovery", state)
        self.assertIn("abcdefgh1234", state)
        self.assertIn("ap", open(self.path("run/wifi-mode")).read())

    def test_add_wifi_network_with_password(self):
        conf = self.write("wpa.conf", "ctrl_interface=/var/run/wpa_supplicant\n")
        self.fake("wpa_passphrase", 'wpa_passphrase*) printf \'network={\\n\\tssid="Hotel"\\n\\t#psk="segredo123"\\n\\tpsk=abcd\\n}\\n\' ;;')
        r = self.sh(f'add_wifi_network "{conf}" Hotel segredo123')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = open(conf).read()
        self.assertIn('ssid="Hotel"', text)
        self.assertIn("psk=abcd", text)
        self.assertIn("priority=20", text)
        self.assertNotIn("segredo123", text)

    def test_add_open_wifi_network(self):
        conf = self.write("wpa.conf", "")
        r = self.sh(f'add_wifi_network "{conf}" Cafe ""')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = open(conf).read()
        self.assertIn("key_mgmt=NONE", text)
        self.assertIn("priority=20", text)
        self.assertIn('ssid=4361666', text)

    def test_add_wifi_network_rejects_short_password(self):
        conf = self.write("wpa.conf", "")
        r = self.sh(f'add_wifi_network "{conf}" Hotel curta')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("8 a 63", r.stdout)

    def test_scan_list_sorted_by_signal_without_repeats(self):
        results = ("bssid / frequency / signal level / flags / ssid\n"
                   "aa:01\t2412\t-70\t[WPA2-PSK-CCMP][ESS]\tCasa\n"
                   "aa:02\t5180\t-45\t[WPA2-PSK-CCMP][ESS]\tCasa\n"
                   "bb:01\t2437\t-60\t[ESS]\tCafe Livre\n"
                   "cc:01\t2462\t-50\t[WPA2-PSK-CCMP][ESS]\t\n")
        r = self.sh("build_scan_list", stdin=results)
        self.assertEqual(r.stdout.splitlines(), ["   -45 dBm  Casa", "   -60 dBm  Cafe Livre"])

    # Ciclo de energia do AIC8800: unbind/bind do host SDIO (mmc-pwrseq baixa e sobe o WL_REG_ON).
    def sdio_env(self, card=True):
        os.makedirs(self.path("platform/fe2c0000.mmc"), exist_ok=True)
        self.write("dwmmc/unbind", "")
        self.write("dwmmc/bind", "")
        if card:
            self.write("sdio/mmc1:390b:1/vendor", "0xc8a1\n")
        return {"WIFI_PLATFORM_DEVICES": self.path("platform"), "WIFI_SDIO_DRIVER": self.path("dwmmc"),
                "WIFI_SDIO_DEVICES": self.path("sdio"), "WIFI_POWER_OFF_SECONDS": "0", "WIFI_CARD_WAIT": "1"}

    def test_power_cycle_unbinds_and_binds_sdio_host(self):
        self.fake("rmmod")
        r = self.sh("power_cycle_wifi_chip", env=self.sdio_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(self.path("dwmmc/unbind")).read().strip(), "fe2c0000.mmc")
        self.assertEqual(open(self.path("dwmmc/bind")).read().strip(), "fe2c0000.mmc")
        self.assertIn("rmmod aic8800_fdrv", self.fake_log())

    def test_power_cycle_reports_card_that_does_not_come_back(self):
        self.fake("rmmod")
        r = self.sh("power_cycle_wifi_chip", env=self.sdio_env(card=False))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("não voltou", r.stdout)


make_suite(globals(), NetworkMixin)
