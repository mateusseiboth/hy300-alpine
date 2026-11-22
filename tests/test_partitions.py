"""Partições por nome (/dev/block/by-name) e o BCB da misc (rootfs/usr/lib/hy300/partitions.sh).

Rodar: python3 -I -m unittest discover -s tests
"""
import os

from shelltest import ShellMixin, make_suite, read_bytes

BCB_SIZE = 2048
MISC_SIZE = 4 * 1024 * 1024


class PartitionsMixin(ShellMixin):
    libs = ("common.sh", "partitions.sh")

    def add_block(self, dev, partname=None, sectors=8):
        lines = ["MAJOR=179", f"DEVNAME={dev}", "DEVTYPE=partition"]
        lines += [f"PARTNAME={partname}"] if partname else []
        self.write(f"sys/{dev}/uevent", "\n".join(lines) + "\n")
        self.write(f"sys/{dev}/size", f"{sectors}\n")

    def env(self):
        return {"HY300_SYSFS_BLOCK": self.path("sys"), "HY300_BY_NAME": self.path("dev/block/by-name")}

    def test_link_partitions_by_name_creates_android_style_links(self):
        self.add_block("mmcblk2p4", "misc")
        self.add_block("mmcblk2p9", "boot")
        self.add_block("mmcblk2", None)
        r = self.sh("link_partitions_by_name", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        links = sorted(os.listdir(self.path("dev/block/by-name")))
        self.assertEqual(links, ["boot", "misc"])
        self.assertEqual(os.readlink(self.path("dev/block/by-name/misc")), "/dev/mmcblk2p4")

    def test_find_partition_by_name(self):
        self.add_block("mmcblk2p4", "misc")
        r = self.sh("find_partition_by_name misc && ! find_partition_by_name super", env=self.env())
        self.assertEqual(r.stdout.strip(), "mmcblk2p4")
        self.assertEqual(r.returncode, 0)

    def test_list_partitions_prints_name_device_and_bytes(self):
        self.add_block("mmcblk2p4", "misc", 8192)
        self.add_block("mmcblk2p9", "boot", 81920)
        r = self.sh("list_partitions", env=self.env())
        self.assertEqual(r.stdout.splitlines(), ["boot mmcblk2p9 41943040", "misc mmcblk2p4 4194304"])

    def write_misc(self, command):
        misc = bytearray(MISC_SIZE)
        misc[:len(command)] = command
        misc[0x800:0x804] = b"\0AB0"
        misc[0x4000:0x4000 + 13] = b"boot-recovery"
        return self.write("misc.img", bytes(misc))

    def test_clear_bcb_if_recovery_zeroes_only_the_bcb(self):
        path = self.write_misc(b"boot-recovery\0recovery\n--wipe_data\0")
        before = read_bytes(path)
        r = self.sh(f'clear_bcb_if_recovery "{path}"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = read_bytes(path)
        self.assertEqual(after[:BCB_SIZE], bytes(BCB_SIZE))
        self.assertEqual(after[BCB_SIZE:], before[BCB_SIZE:])
        self.assertIn("apagado", r.stdout)

    def test_clear_bcb_keeps_other_commands(self):
        path = self.write_misc(b"bootonce-bootloader\0")
        before = read_bytes(path)
        r = self.sh(f'clear_bcb_if_recovery "{path}"')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read_bytes(path), before)
        self.assertIn("mantido", r.stdout)

    def test_clear_bcb_keeps_empty_misc(self):
        path = self.write_misc(b"")
        r = self.sh(f'clear_bcb_if_recovery "{path}"')
        self.assertNotEqual(r.returncode, 0)

    def test_is_misc_size_expected(self):
        self.add_block("mmcblk2p4", "misc", 8192)
        self.add_block("mmcblk2p5", "misc2", 8)
        r = self.sh("is_misc_size_expected mmcblk2p4 && ! is_misc_size_expected mmcblk2p5", env=self.env())
        self.assertEqual(r.returncode, 0)


make_suite(globals(), PartitionsMixin)
