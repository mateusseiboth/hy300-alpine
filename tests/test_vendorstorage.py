"""hy300-vendorstorage (src/hy300-vendorstorage.c) e hy300-orientacao.

O programa fala com o /dev/vendor_storage do driver de vendor storage do eMMC da Rockchip
(sdmmc_vendor_storage.c do hy300-6.1) pelo ioctl VENDOR_READ_IO/VENDOR_WRITE_IO, com a struct
RK_VENDOR_REQ (tag, id, len, data[1024]) de include/uapi/misc/rkflash_vendor_storage.h. No host
ele compila com um ioctl falso (tests/c/fake_vendor_ioctl.c) que imita o driver; um teste à
parte confere os números do ioctl e a struct contra o cabeçalho do próprio kernel.

O id 50 é o modo de instalação que o U-Boot da TXCZ lê (1 byte ASCII; '2' ou '3' = teto, logo
girado 180°). hy300-orientacao [0|1|2|3] mostra ou grava esse byte.

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "src", "hy300-vendorstorage.c")
FAKE = os.path.join(HERE, "c", "fake_vendor_ioctl.c")
ORIENTACAO = os.path.join(REPO, "rootfs", "usr", "sbin", "hy300-orientacao")
KSRC = os.environ.get("KSRC", os.path.expanduser("~/hy300-work/kernel-recovery-wt"))
UAPI = os.path.join(KSRC, "include", "uapi", "misc", "rkflash_vendor_storage.h")

ABI_CHECK = r"""
#include <stddef.h>
#include <stdio.h>
#include "rkflash_vendor_storage.h"
int main(void)
{
	printf("%lu %lu %lu %lu %lu 0x%lx 0x%lx 0x%x\n", sizeof(struct RK_VENDOR_REQ),
	       offsetof(struct RK_VENDOR_REQ, tag), offsetof(struct RK_VENDOR_REQ, id),
	       offsetof(struct RK_VENDOR_REQ, len), offsetof(struct RK_VENDOR_REQ, data),
	       (unsigned long)VENDOR_READ_IO, (unsigned long)VENDOR_WRITE_IO, VENDOR_REQ_TAG);
	return 0;
}
"""


@unittest.skipUnless(shutil.which("gcc"), "sem gcc no host")
class VendorStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hy300-vs-")
        cls.bin = os.path.join(cls.tmp, "hy300-vendorstorage")
        subprocess.run(["gcc", "-std=c11", "-D_GNU_SOURCE", "-DHY300_VS_FAKE_IOCTL", "-Wall", "-Wextra", "-Werror",
                        "-O2", "-o", cls.bin, SRC, FAKE], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def setUp(self):
        self.store = tempfile.mkdtemp(dir=self.tmp)
        self.dev = os.path.join(self.store, "vendor_storage")
        open(self.dev, "wb").close()

    def put(self, item_id, data):
        with open(os.path.join(self.store, str(item_id)), "wb") as f:
            f.write(data)

    def get(self, item_id):
        with open(os.path.join(self.store, str(item_id)), "rb") as f:
            return f.read()

    def calls(self):
        path = os.path.join(self.store, "log")
        return open(path).read().splitlines() if os.path.exists(path) else []

    def run_vs(self, *args):
        env = dict(os.environ, FAKE_VENDOR_DIR=self.store)
        return subprocess.run([self.bin, "-d", self.dev, *args], capture_output=True, env=env, timeout=10)

    def test_read_prints_item_bytes(self):
        self.put(50, b"2")
        r = self.run_vs("read", "50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b"2")
        self.assertIn("cmd=0x40047601 tag=0x56524551 id=50 len=1024", self.calls())

    def test_read_hex(self):
        self.put(1, b"\x01\xab")
        r = self.run_vs("read", "--hex", "1")
        self.assertEqual(r.stdout.decode().strip(), "01ab")

    def test_read_missing_item_fails(self):
        r = self.run_vs("read", "77")
        self.assertEqual(r.returncode, 1)
        self.assertIn("77", r.stderr.decode())

    def test_write_then_verify_reading_back(self):
        r = self.run_vs("write", "50", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.get(50), b"0")
        self.assertEqual([c.split()[0] for c in self.calls()], ["cmd=0x40047602", "cmd=0x40047601"])
        self.assertIn("cmd=0x40047602 tag=0x56524551 id=50 len=1", self.calls())

    def test_write_hex(self):
        r = self.run_vs("write", "--hex", "9", "00ff10")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.get(9), b"\x00\xff\x10")

    def test_rejects_bad_arguments(self):
        for args in ([], ["read"], ["read", "abc"], ["read", "70000"], ["write", "50"], ["write", "--hex", "1", "0g"],
                     ["apaga", "50"]):
            r = self.run_vs(*args)
            self.assertEqual(r.returncode, 2, args)

    def test_missing_device_fails(self):
        r = subprocess.run([self.bin, "-d", os.path.join(self.tmp, "nao-existe"), "read", "50"],
                           capture_output=True, timeout=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"vendor storage", r.stderr)

    @unittest.skipUnless(os.path.isfile(UAPI), "sem o cabeçalho do kernel hy300-6.1")
    def test_abi_matches_kernel_header(self):
        check = os.path.join(self.tmp, "abi.c")
        with open(check, "w") as f:
            f.write(ABI_CHECK)
        exe = os.path.join(self.tmp, "abi")
        subprocess.run(["gcc", "-I", os.path.dirname(UAPI), "-o", exe, check], check=True)
        out = subprocess.run([exe], capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, ["1032", "0", "4", "6", "8", "0x40047601", "0x40047602", "0x56524551"])

    # hy300-orientacao: mostra ou grava o id 50 com o vendor storage falso.
    def orientacao(self, *args):
        env = dict(os.environ, FAKE_VENDOR_DIR=self.store, HY300_VENDORSTORAGE=f"{self.bin} -d {self.dev}",
                   HY300_LIB=os.path.join(REPO, "rootfs", "usr", "lib", "hy300"), KMSG=os.path.join(self.store, "kmsg"))
        return subprocess.run(["sh", ORIENTACAO, *args], capture_output=True, text=True, env=env, timeout=10)

    def test_orientacao_shows_current_mode(self):
        self.put(50, b"2")
        r = self.orientacao()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2", r.stdout)
        self.assertIn("teto", r.stdout)
        self.assertIn("girado", r.stdout)

    def test_orientacao_writes_table_mode(self):
        self.put(50, b"2")
        r = self.orientacao("0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.get(50), b"0")
        self.assertIn("mesa", r.stdout)

    def test_orientacao_rejects_other_values(self):
        self.put(50, b"2")
        for value in ("4", "teto", "-1", "00"):
            r = self.orientacao(value)
            self.assertEqual(r.returncode, 2, value)
        self.assertEqual(self.get(50), b"2")


if __name__ == "__main__":
    unittest.main()
