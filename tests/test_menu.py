"""Menu local da recuperação no tty1, pelo teclado USB (rootfs/usr/lib/hy300/menu.sh).

Teclas numéricas, uma por vez: 2 Android, 3 escolher rede Wi-Fi, 4 shell; qualquer outra
coisa (ou o tempo) só atualiza a tela. A escolha de rede numera as redes do scan.

Rodar: python3 -I -m unittest discover -s tests
"""
from shelltest import ShellMixin, make_suite

SCAN = ("  -40 dBm  Casa\n  -62 dBm  Vizinho 5G\n  -80 dBm  Cafe\n")


class MenuMixin(ShellMixin):
    libs = ("common.sh", "menu.sh")

    def test_menu_action_by_key(self):
        r = self.sh("for k in 1 2 3 4 5 x ''; do read_menu_action \"$k\"; done")
        self.assertEqual(r.stdout.split(), ["atualizar", "android", "rede", "shell", "grafico", "atualizar", "atualizar"])

    def test_menu_lines_list_the_options(self):
        text = self.sh("build_menu_lines").stdout
        for option in ("2 Iniciar o Android", "3 Escolher rede", "4 Shell", "5 Ambiente gráfico"):
            self.assertIn(option, text)
        self.assertNotIn("—", text)

    def test_network_list_is_numbered(self):
        r = self.sh("build_network_list", stdin=SCAN)
        self.assertEqual(r.stdout.splitlines(), ["  1  Casa (-40 dBm)", "  2  Vizinho 5G (-62 dBm)", "  3  Cafe (-80 dBm)"])

    def test_network_by_number(self):
        r = self.sh("read_network_by_number 2", stdin=SCAN)
        self.assertEqual(r.stdout, "Vizinho 5G\n")
        r = self.sh("read_network_by_number 9", stdin=SCAN)
        self.assertNotEqual(r.returncode, 0)

    def test_network_list_keeps_at_most_nine(self):
        scan = "".join(f"  -{50 + i} dBm  Rede{i}\n" for i in range(12))
        r = self.sh("build_network_list", stdin=scan)
        self.assertEqual(len(r.stdout.splitlines()), 9)


make_suite(globals(), MenuMixin)
