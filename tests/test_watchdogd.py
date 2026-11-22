"""hy300-watchdogd (src/hy300-watchdogd.c): alimenta o watchdog com pré-timeout.

Com o pré-timeout o dw_wdt do RK3566 entra no modo de interrupção: no fim do prazo vem uma
interrupção, o governador "panic" do kernel dá panic e o aparelho reinicia pelo caminho normal
(com log no pstore). Só se nem a interrupção for atendida o reset de hardware acontece, um prazo
depois. Ao receber SIGTERM o daemon escreve 'V' (fechamento mágico) e sai.

Sem um watchdog de verdade no host, o "dispositivo" é um arquivo: os ioctl falham e o daemon
alimenta escrevendo nele (o que também vale para o /dev/watchdog).

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src", "hy300-watchdogd.c")


@unittest.skipUnless(shutil.which("gcc"), "sem gcc no host")
class WatchdogdTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hy300-watchdogd-")
        cls.bin = os.path.join(cls.tmp, "hy300-watchdogd")
        subprocess.run(["gcc", "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-O2",
                        "-o", cls.bin, SRC], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def setUp(self):
        self.dev = os.path.join(self.tmp, f"watchdog-{self.id()}")
        open(self.dev, "wb").close()

    def read_dev(self):
        with open(self.dev, "rb") as f:
            return f.read()

    def test_feeds_and_closes_with_magic_on_sigterm(self):
        proc = subprocess.Popen([self.bin, "-T", "30", "-P", "30", "-t", "1", self.dev],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(2.5)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err)
        data = self.read_dev()
        self.assertGreaterEqual(len(data), 3, data)
        self.assertEqual(data[-1:], b"V")
        self.assertIn("pré-timeout", err)

    def test_rejects_bad_arguments(self):
        for args in ([], ["-T", "0", self.dev], ["-t", "x", self.dev], ["-T", "10", "-t", "20", self.dev]):
            r = subprocess.run([self.bin, *args], capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 2, args)

    def test_missing_device_fails(self):
        r = subprocess.run([self.bin, os.path.join(self.tmp, "nao-existe")], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
