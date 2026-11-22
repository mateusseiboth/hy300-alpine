"""hy300-wifi connect: a rede nova vai para o wpa_supplicant.conf da RAM, para a backup e pede
ao daemon que reconecte.

Rodar: python3 -I -m unittest discover -s tests
"""
import os

from shelltest import REPO, ShellMixin, make_suite

WIFI = os.path.join(REPO, "rootfs", "usr", "sbin", "hy300-wifi")
PASSPHRASE_OUTPUT = 'network={\\n\\tssid="Hotel"\\n\\t#psk="segredo123"\\n\\tpsk=abcd\\n}\\n'


class WifiCommandMixin(ShellMixin):
    libs = ("common.sh",)

    def setUp(self):
        super().setUp()
        self.fake("wpa_passphrase", f"wpa_passphrase*) printf '{PASSPHRASE_OUTPUT}' ;;")
        self.fake("mount")
        self.fake("sync")
        self.fake("mountpoint", 'mountpoint*) [ -d "$HY300_BACKUP/config" ] ;;')
        self.conf = self.write("wpa.conf", "ctrl_interface=/var/run/wpa_supplicant\n")
        os.makedirs(self.path("backup/config"))

    def test_connect_saves_in_ram_and_backup_and_requests_station(self):
        env = {"HY300_BACKUP": self.path("backup"), "WIFI_WPA_CONF_OVERRIDE": self.conf}
        r = self.sh(f'sh "{WIFI}" connect Hotel segredo123', env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ram = open(self.conf).read()
        saved = open(self.path("backup/config/redes.conf")).read()
        self.assertIn("psk=abcd", ram)
        self.assertIn("psk=abcd", saved)
        self.assertNotIn("segredo123", ram + saved)
        self.assertEqual(open(self.path("run/wifi-request")).read().strip(), "station")


make_suite(globals(), WifiCommandMixin)
