"""hy300-flash: grava uma imagem numa partição por nome e confere lendo de volta.

As "partições" são arquivos em HY300_BY_NAME; o tamanho vem do arquivo (blockdev falso).

Rodar: python3 -I -m unittest discover -s tests
"""
import hashlib
import os

from shelltest import REPO, ShellMixin, make_suite, read_bytes

FLASH = os.path.join(REPO, "rootfs", "usr", "sbin", "hy300-flash")


class FlashMixin(ShellMixin):
    libs = ("common.sh",)

    def setUp(self):
        super().setUp()
        self.fake("blockdev", 'blockdev\\ --getsize64*) for last; do :; done; wc -c <"$last" | tr -d " " ;;')
        self.fake("sync")
        self.part = self.write("by-name/boot", b"\xff" * 65536)
        self.write("by-name/uboot", b"\xee" * 4096)
        self.write("mounts", "overlay / overlay rw 0 0\n")

    def flash(self, *args, stdin=None):
        quoted = " ".join(f"'{a}'" for a in args)
        env = {"HY300_BY_NAME": self.path("by-name"), "HY300_MOUNTS": self.path("mounts")}
        return self.sh(f'sh "{FLASH}" {quoted}', env=env, stdin=stdin)

    def test_writes_file_and_verifies(self):
        img = self.write("new.img", b"NEW" * 1000)
        r = self.flash("boot", img)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = read_bytes(self.part)
        self.assertEqual(data[:3000], b"NEW" * 1000)
        self.assertEqual(data[3000:], b"\xff" * (65536 - 3000))
        self.assertIn("conferida", r.stdout)

    def test_refuses_image_bigger_than_partition(self):
        img = self.write("big.img", b"X" * 70000)
        r = self.flash("boot", img)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read_bytes(self.part), b"\xff" * 65536)
        self.assertIn("maior", r.stdout)

    def test_refuses_unknown_partition(self):
        img = self.write("new.img", b"NEW")
        r = self.flash("nao-existe", img)
        self.assertNotEqual(r.returncode, 0)

    def test_protected_partition_needs_force(self):
        img = self.write("u.img", b"U" * 100)
        r = self.flash("uboot", img)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--force", r.stdout)
        r = self.flash("--force", "uboot", img)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_refuses_mounted_partition(self):
        os.remove(self.part)
        os.symlink(self.write("mmcblk2p9", b"\xff" * 65536), self.part)
        self.write("mounts", f"{self.path('mmcblk2p9')} /media/backup ext4 ro 0 0\n")
        img = self.write("new.img", b"NEW")
        r = self.flash("boot", img)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("montada", r.stdout)

    def test_stdin_needs_size_and_hash(self):
        data = b"STREAM" * 500
        r = self.flash("boot", "-", stdin=data)
        self.assertNotEqual(r.returncode, 0)
        digest = hashlib.sha256(data).hexdigest()
        r = self.flash("--size", str(len(data)), "--sha256", digest, "boot", "-", stdin=data)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_bytes(self.part)[:len(data)], data)

    def test_stdin_with_wrong_hash_fails_loudly(self):
        data = b"STREAM" * 500
        r = self.flash("--size", str(len(data)), "--sha256", "0" * 64, "boot", "-", stdin=data)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("NÃO confere", r.stdout)


make_suite(globals(), FlashMixin)
