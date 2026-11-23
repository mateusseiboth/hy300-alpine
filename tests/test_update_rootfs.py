"""hy300-update-rootfs: troca o rootfs.sqfs da partição backup com o Alpine rodando.

Copia o arquivo novo para rootfs.sqfs.novo, confere o SHA-256, põe no lugar (o antigo, aberto
pelo loop até o reboot, fica como rootfs.sqfs.anterior) e grava o .sha256; a backup fica rw só
nesse tempo.

Rodar: python3 -I -m unittest discover -s tests
"""
import hashlib
import os

from shelltest import REPO, ShellMixin, make_suite, read_bytes

UPDATE = os.path.join(REPO, "rootfs", "usr", "sbin", "hy300-update-rootfs")


class UpdateRootfsMixin(ShellMixin):
    libs = ("common.sh",)

    def setUp(self):
        super().setUp()
        self.fake("mount")
        self.fake("sync")
        self.fake("mountpoint", 'mountpoint*) [ -d "$HY300_BACKUP/config" ] ;;')
        self.write("backup/config/redes.conf", "")
        self.write("backup/rootfs.sqfs", b"VELHO")

    def update(self, *args):
        quoted = " ".join(f"'{a}'" for a in args)
        return self.sh(f'sh "{UPDATE}" {quoted}', env={"HY300_BACKUP": self.path("backup")})

    def test_replaces_rootfs_and_hash(self):
        new = self.write("novo.sqfs", b"NOVO" * 100)
        digest = hashlib.sha256(b"NOVO" * 100).hexdigest()
        r = self.update(new, digest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_bytes(self.path("backup/rootfs.sqfs")), b"NOVO" * 100)
        self.assertTrue(read_bytes(self.path("backup/rootfs.sqfs.sha256")).startswith(digest.encode()))
        mounts = [line for line in self.fake_log() if line.startswith("mount ")]
        self.assertEqual([m.split()[2] for m in mounts], ["remount,rw", "remount,ro"])

    def test_old_rootfs_stays_linked_as_anterior(self):
        # Apagar o antigo, ainda aberto pelo loop, deixa um órfão no ext4: a backup não volta a
        # só-leitura e o estágio 1 não monta mais a partição no boot seguinte.
        new = self.write("novo.sqfs", b"NOVO")
        r = self.update(new, hashlib.sha256(b"NOVO").hexdigest())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_bytes(self.path("backup/rootfs.sqfs.anterior")), b"VELHO")

    def test_previous_anterior_is_replaced(self):
        self.write("backup/rootfs.sqfs.anterior", b"MAIS-VELHO")
        new = self.write("novo.sqfs", b"NOVO")
        self.update(new, hashlib.sha256(b"NOVO").hexdigest())
        self.assertEqual(read_bytes(self.path("backup/rootfs.sqfs.anterior")), b"VELHO")

    def test_warns_when_backup_stays_writable(self):
        self.fake("mount", 'mount*remount,ro*) exit 32 ;;')
        new = self.write("novo.sqfs", b"NOVO")
        r = self.update(new, hashlib.sha256(b"NOVO").hexdigest())
        self.assertIn("continua gravável", r.stdout)

    def test_wrong_hash_keeps_old_rootfs(self):
        new = self.write("novo.sqfs", b"NOVO")
        r = self.update(new, "0" * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read_bytes(self.path("backup/rootfs.sqfs")), b"VELHO")
        self.assertFalse(os.path.exists(self.path("backup/rootfs.sqfs.novo")))
        self.assertIn("remount,ro", " ".join(self.fake_log()))


make_suite(globals(), UpdateRootfsMixin)
