"""Configuração persistente na partição backup (rootfs/usr/lib/hy300/persist.sh).

A backup é ext4 montada só-leitura em /media/backup; para salvar, remonta rw por um instante,
grava, sync e volta a só-leitura. As redes Wi-Fi acrescentadas ficam em config/redes.conf e
são somadas ao wpa_supplicant.conf do build em todo boot. O mount é falso.

Rodar: python3 -I -m unittest discover -s tests
"""
import os

from shelltest import ShellMixin, make_suite

BLOCK = 'network={\n\tssid="Hotel"\n\tpsk=abcd\n\tpriority=20\n}\n'


class PersistMixin(ShellMixin):
    libs = ("common.sh", "persist.sh")

    def setUp(self):
        super().setUp()
        self.fake("mount")
        self.fake("mountpoint", 'mountpoint*) [ -d "$HY300_BACKUP/config" ] ;;')
        self.fake("sync")

    def env(self):
        return {"HY300_BACKUP": self.path("backup")}

    def test_without_backup_nothing_is_saved(self):
        block = self.write("bloco", BLOCK)
        r = self.sh(f'save_wifi_block "{block}"', env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("só na RAM", r.stdout)

    def test_save_remounts_rw_then_ro(self):
        os.makedirs(self.path("backup/config"))
        block = self.write("bloco", BLOCK)
        r = self.sh(f'save_wifi_block "{block}"', env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(self.path("backup/config/redes.conf")).read(), BLOCK)
        log = [line for line in self.fake_log() if line.startswith("mount ")]
        backup = self.path("backup")
        self.assertEqual(log, [f"mount -o remount,rw {backup}", f"mount -o remount,ro {backup}"])

    def test_restore_appends_saved_networks_to_build_conf(self):
        os.makedirs(self.path("backup/config"))
        self.write("backup/config/redes.conf", BLOCK)
        conf = self.write("wpa.conf", "ctrl_interface=/var/run/wpa_supplicant\n")
        r = self.sh(f'restore_wifi_networks "{conf}"', env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(conf).read(), "ctrl_interface=/var/run/wpa_supplicant\n" + BLOCK)

    def test_restore_without_saved_networks_keeps_conf(self):
        conf = self.write("wpa.conf", "x=1\n")
        self.sh(f'restore_wifi_networks "{conf}"', env=self.env())
        self.assertEqual(open(conf).read(), "x=1\n")


make_suite(globals(), PersistMixin)
