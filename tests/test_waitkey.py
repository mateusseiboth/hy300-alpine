"""hy300-waitkey (src/hy300-waitkey.c): espera uma tecla de TECLADO com prazo e diz qual foi.

No aparelho (teste 1) o autoboot ficou no Alpine sem ninguém por perto: o receptor IR capta
ruído, e havia também teclas do painel, de energia, o mouse e o "Consumer Control" do receptor
2.4G. Agora só conta EV_KEY com valor 1 (apertar), código de tecla de teclado (KEY_ESC a
KEY_MICMUTE, sem BTN_*), vindo de um teclado de verdade: nome fora da lista de ignorados e com
letras no mapa de teclas.

Compila com o gcc do host. Os "dispositivos" dos testes de eventos são arquivos com struct
input_event (24 bytes em 64 bits), passados com --all (arquivo não responde aos ioctl de
nome e mapa de teclas). A classificação é testada com --classify NOME CÓDIGOS...

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import shutil
import struct
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src", "hy300-waitkey.c")
EV_SYN, EV_KEY, EV_ABS, EV_MSC = 0, 1, 3, 4
KEY_ENTER, KEY_A, KEY_Z, KEY_SPACE, KEY_DOWN, KEY_REPLY, KEY_POWER = 28, 30, 44, 57, 108, 232, 116
KEY_OK = 352
BTN_LEFT = 272
LETTERS = [str(code) for code in (16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 30, 31, 32, 33, 34, 35, 36, 37, 38,
                                  44, 45, 46, 47, 48, 49, 50, KEY_SPACE, KEY_ENTER)]


def build_event(ev_type, code, value):
    return struct.pack("<qqHHi", 0, 0, ev_type, code, value)


@unittest.skipUnless(shutil.which("gcc"), "sem gcc no host")
class WaitkeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hy300-waitkey-")
        cls.bin = os.path.join(cls.tmp, "hy300-waitkey")
        subprocess.run(["gcc", "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-O2",
                        "-o", cls.bin, SRC], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def device(self, name, *events):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(b"".join(events))
        return path

    def run_waitkey(self, *args):
        start = time.monotonic()
        r = subprocess.run([self.bin, *args], capture_output=True, text=True, timeout=10)
        return r, time.monotonic() - start

    def classify(self, name, *codes):
        r = subprocess.run([self.bin, "--classify", name, *codes], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()

    def test_key_press_ends_wait_and_says_code_and_device(self):
        dev = self.device("kbd", build_event(EV_KEY, KEY_A, 1), build_event(EV_SYN, 0, 0))
        r, elapsed = self.run_waitkey("--all", "5", dev)
        self.assertEqual(r.returncode, 0, r.stderr)
        fields = r.stdout.splitlines()[-1].split(" ", 3)
        self.assertEqual(fields[:2], ["tecla", str(KEY_A)])
        self.assertTrue(fields[2].isdigit(), fields)
        self.assertEqual(fields[3], dev)
        self.assertLess(elapsed, 1)

    def test_only_press_counts_not_release_or_autorepeat(self):
        dev = self.device("kbd", build_event(EV_KEY, KEY_A, 0), build_event(EV_KEY, KEY_DOWN, 2))
        r, _ = self.run_waitkey("--all", "1", dev)
        self.assertEqual(r.stdout.splitlines()[-1], "tempo")

    def test_mouse_buttons_and_non_keyboard_codes_do_not_count(self):
        dev = self.device("mouse", build_event(EV_KEY, BTN_LEFT, 1), build_event(EV_KEY, KEY_OK, 1),
                          build_event(EV_MSC, 4, 1))
        r, _ = self.run_waitkey("--all", "1", dev)
        self.assertEqual(r.stdout.splitlines()[-1], "tempo")

    def test_motion_does_not_count(self):
        gsensor = self.device("gsensor", *[build_event(EV_ABS, 0, 100 + i) for i in range(50)])
        r, elapsed = self.run_waitkey("--all", "1", gsensor)
        self.assertEqual(r.returncode, 1)
        self.assertGreaterEqual(elapsed, 0.9)

    def test_without_all_a_file_is_not_a_keyboard(self):
        dev = self.device("kbd2", build_event(EV_KEY, KEY_A, 1))
        r, _ = self.run_waitkey("1", dev)
        self.assertEqual(r.stdout.splitlines()[-1], "tempo")

    def test_counts_down_each_second(self):
        r, _ = self.run_waitkey("3", os.path.join(self.tmp, "nao-existe"))
        self.assertEqual(r.stdout.splitlines(), ["3", "2", "1", "tempo"])

    def test_zero_seconds_returns_time_out(self):
        r, elapsed = self.run_waitkey("0")
        self.assertEqual(r.stdout.splitlines(), ["tempo"])
        self.assertLess(elapsed, 0.5)

    def test_rejects_bad_seconds(self):
        r, _ = self.run_waitkey("cinco")
        self.assertEqual(r.returncode, 2)

    def test_classify_the_hy300_input_devices(self):
        ignored = {
            "fdd70030.pwm": [str(KEY_REPLY), "103", "108", "2", "3"],
            "adc-keys": ["103", "108", "105", "106", str(KEY_ENTER), "158"],
            "gpio-keys": [str(KEY_POWER)],
            "bt-powerkey": [str(KEY_POWER)],
            "2.4G Composite Devic Mouse": ["272", "273", "274"],
            "2.4G Composite Devic Consumer Control": ["113", "114", "115", "163", "164"],
            "2.4G Composite Devic System Control": ["142", "143", "116"],
        }
        for name, codes in ignored.items():
            self.assertEqual(self.classify(name, *codes), "ignorado", name)
        self.assertEqual(self.classify("2.4G Composite Devic", *LETTERS), "teclado")
        self.assertEqual(self.classify("Logitech USB Keyboard", *LETTERS), "teclado")
        self.assertEqual(self.classify("Controle sem letras", "103", "108", str(KEY_ENTER)), "ignorado")


if __name__ == "__main__":
    unittest.main()
