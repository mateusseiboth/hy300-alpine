"""Tela de status da recuperação (rootfs/usr/lib/hy300/screen.sh).

Com a fonte Terminus 16x32 o painel de 1024x600 tem 64x18 caracteres: o texto precisa caber,
dizer o IP e o comando de ssh, e não leva travessão.

Rodar: python3 -I -m unittest discover -s tests
"""
from shelltest import ShellMixin, make_suite

COLUMNS = 64
ROWS = 18


class ScreenMixin(ShellMixin):
    libs = ("common.sh", "screen.sh", "menu.sh")

    def build(self, *args):
        quoted = " ".join(f"'{a}'" for a in args)
        r = self.sh(f"build_status_text {quoted}")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_status_with_wifi_and_cable(self):
        text = self.build("3.24.4", "boot", "recovery", "wlan0 192.0.2.10 conectado", "eth0 10.0.0.7", "12", "61", "1210")
        self.assertIn("Alpine 3.24.4", text)
        self.assertIn("ssh root@192.0.2.10", text)
        self.assertIn("192.0.2.10", text)
        self.assertIn("10.0.0.7", text)
        self.assertIn("61 °C", text)

    def test_status_without_address_explains_what_to_do(self):
        text = self.build("3.24.4", "recovery", "boot", "wlan0 - FALHOU: sem conexão", "", "1", "55", "1300")
        self.assertNotIn("ssh root@", text)
        self.assertIn("Sem rede", text)

    def test_ssh_line_prefers_wifi_then_cable(self):
        text = self.build("3.24.4", "boot", "recovery", "wlan0 - associando", "eth0 10.0.0.7", "1", "55", "1300")
        self.assertIn("ssh root@10.0.0.7", text)

    def test_access_point_shows_network_and_password(self):
        text = self.build("3.24.4", "boot", "recovery", "wlan0 192.168.50.1 ponto de acesso", "", "3", "60", "1200",
                          "HY300-6bot-recovery k3J9pQ2xW7mZ")
        self.assertIn("HY300-6bot-recovery", text)
        self.assertIn("k3J9pQ2xW7mZ", text)
        self.assertIn("ssh root@192.168.50.1", text)

    def test_text_fits_the_screen_and_has_no_dash(self):
        text = self.build("3.24.4", "recovery", "boot", "wlan0 192.168.100.200 conectado", "eth0 172.16.100.200", "100", "70", "999",
                          "HY300-6bot-recovery k3J9pQ2xW7mZ")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), ROWS)
        self.assertTrue(all(len(line) <= COLUMNS for line in lines), lines)
        self.assertNotIn("—", text)

    def main_screen(self, *status):
        quoted = " ".join(f"'{a}'" for a in status)
        r = self.sh(f"build_main_screen {quoted}", env={})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_main_screen_starts_with_6bot_logo_then_menu(self):
        text = self.main_screen("3.24.4", "boot", "recovery", "wlan0 192.0.2.10 conectado em Casa", "", "3", "60", "1200")
        lines = text.splitlines()
        logo = self.sh("build_logo").stdout.splitlines()
        self.assertEqual(lines[:len(logo)], logo)
        self.assertGreaterEqual(len(logo), 4)
        self.assertIn("ssh root@192.0.2.10", text)
        self.assertLess(text.index("ssh root@"), text.index("2 Iniciar o Android"))

    def test_rescue_mode_is_shown(self):
        text = self.build("3.24.4", "boot", "recovery", "wlan0 - procurando", "", "1", "50", "1300", "",
                          "MODO DE RESGATE: partição backup sem o Alpine")
        self.assertIn("MODO DE RESGATE: partição backup sem o Alpine", text)

    def test_main_screen_fits_in_the_worst_case(self):
        text = self.main_screen("3.24.4", "recovery", "boot", "wlan0 192.168.100.200 conectado em Uma Rede Longa",
                                "eth0 172.16.100.200", "100", "70", "999", "HY300-6bot-recovery k3J9pQ2xW7mZ",
                                "MODO DE RESGATE: rootfs.sqfs não confere com o sha256")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), ROWS, text)
        self.assertTrue(all(len(line) <= COLUMNS for line in lines), lines)
        self.assertNotIn("\u2014", text)


make_suite(globals(), ScreenMixin)
