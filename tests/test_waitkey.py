"""hy300-waitkey (src/hy300-waitkey.c): espera uma tecla nos /dev/input/event* com prazo e
diz qual foi ("tecla <código>").

Compila com o gcc do host. Os "dispositivos" do teste são arquivos com struct input_event
(24 bytes em 64 bits: timeval, tipo, código, valor), o mesmo layout do aarch64.

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
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
KEY_OK = 352
KEY_DOWN = 108


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

    def test_key_press_ends_wait_at_once(self):
        dev = self.device("kbd", build_event(EV_KEY, KEY_OK, 1), build_event(EV_SYN, 0, 0))
        r, elapsed = self.run_waitkey("5", dev)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[-1], f"tecla {KEY_OK}")
        self.assertLess(elapsed, 1)

    def test_reports_first_pressed_key_code(self):
        dev = self.device("ir", build_event(EV_KEY, KEY_OK, 0), build_event(EV_KEY, KEY_DOWN, 1),
                          build_event(EV_KEY, KEY_OK, 1))
        r, _ = self.run_waitkey("5", dev)
        self.assertEqual(r.stdout.splitlines()[-1], f"tecla {KEY_DOWN}")

    def test_autorepeat_counts(self):
        dev = self.device("kbd", build_event(EV_KEY, KEY_DOWN, 2))
        r, _ = self.run_waitkey("5", dev)
        self.assertEqual(r.stdout.splitlines()[-1], f"tecla {KEY_DOWN}")

    def test_motion_and_key_release_do_not_count(self):
        gsensor = self.device("gsensor", *[build_event(EV_ABS, 0, 100 + i) for i in range(50)])
        release = self.device("ir", build_event(EV_KEY, KEY_OK, 0))
        r, elapsed = self.run_waitkey("1", gsensor, release)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines()[-1], "tempo")
        self.assertGreaterEqual(elapsed, 0.9)

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


if __name__ == "__main__":
    unittest.main()
