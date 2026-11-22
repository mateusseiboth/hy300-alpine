"""Proposta para o lado do Android (android/clear-bcb): com o Alpine na boot e o Android na
recovery, um "adb reboot recovery" ou "redefinir para a fábrica" grava boot-recovery no BCB, e
o U-Boot passaria a subir sempre a recovery. O script apaga esse comando no boot do Android.

Roda o script no /bin/sh do host (no aparelho é o sh do toybox/mksh), com uma misc de arquivo.

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "android", "clear-bcb", "hy300-clear-bcb.sh")
MISC_SIZE = 4 * 1024 * 1024


class AndroidClearBcbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hy300-bcb-")
        self.misc = os.path.join(self.tmp, "misc")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_misc(self, command):
        data = bytearray(MISC_SIZE)
        data[:len(command)] = command
        data[0x4000:0x4000 + 13] = b"boot-recovery"
        with open(self.misc, "wb") as f:
            f.write(data)
        return bytes(data)

    def run_script(self):
        return subprocess.run(["sh", SCRIPT], env={"PATH": os.environ["PATH"], "HY300_MISC": self.misc,
                                                   "HY300_LOG": os.path.join(self.tmp, "log")},
                              capture_output=True, text=True, timeout=30)

    def read_misc(self):
        with open(self.misc, "rb") as f:
            return f.read()

    def test_clears_boot_recovery_only_in_bcb(self):
        before = self.write_misc(b"boot-recovery\0recovery\n--wipe_data\0")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.read_misc()
        self.assertEqual(after[:2048], bytes(2048))
        self.assertEqual(after[2048:], before[2048:])

    def test_keeps_other_commands(self):
        before = self.write_misc(b"bootonce-bootloader\0")
        self.run_script()
        self.assertEqual(self.read_misc(), before)


if __name__ == "__main__":
    unittest.main()
