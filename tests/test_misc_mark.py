"""Marca de "ficar no Alpine" de uso único na misc (rootfs/usr/lib/hy300/misc_mark.sh).

16 bytes no offset 0x10000 da misc (4 MiB): "hy300-ficar\\0" + versão 1 (01 00 00 00). Na
misc de fábrica só há dados em 0x0-0xfff (BCB e dados A/B da Rockchip) e em 0x4000 (BCB
legado); de 0x8000 em diante é zero. O Alpine só aceita o valor exato, apaga a marca antes de
qualquer outra coisa (sem laço) e fica sem contagem. hy300-ficar grava a marca para o próximo
boot; o scripts/reboot-to-alpine.sh a grava pelo Android.

Rodar: python3 -I -m unittest discover -s tests
"""
import os

from shelltest import REPO, ShellMixin, make_suite, read_bytes

MISC_SIZE = 4 * 1024 * 1024
OFFSET = 0x10000
COUNTER = 0x10010
MARK = b"hy300-ficar\0\x01\0\0\0"
FICAR = os.path.join(REPO, "rootfs", "usr", "sbin", "hy300-ficar")


class MiscMarkMixin(ShellMixin):
    libs = ("common.sh", "misc_mark.sh")

    def write_misc(self, at_offset=b""):
        misc = bytearray(MISC_SIZE)
        misc[:13] = b"boot-recovery"
        misc[0x800:0x804] = b"\0AB0"
        misc[0x4000:0x400d] = b"boot-recovery"
        misc[OFFSET:OFFSET + len(at_offset)] = at_offset
        return self.write("misc.img", bytes(misc))

    def test_mark_is_found_and_cleared_without_touching_the_rest(self):
        path = self.write_misc(MARK)
        before = read_bytes(path)
        r = self.sh(f'is_stay_mark_present "{path}" && clear_stay_mark "{path}" && ! is_stay_mark_present "{path}"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = read_bytes(path)
        self.assertEqual(after[OFFSET:OFFSET + 16], bytes(16))
        self.assertEqual(after[:OFFSET], before[:OFFSET])
        self.assertEqual(after[OFFSET + 16:], before[OFFSET + 16:])

    def test_only_the_exact_value_counts(self):
        for value in (b"hy300-ficar\0\x02\0\0\0", b"hy300-ficar", b"HY300-FICAR\0\x01\0\0\0", b"\xff" * 16):
            path = self.write_misc(value)
            r = self.sh(f'is_stay_mark_present "{path}"')
            self.assertNotEqual(r.returncode, 0, value)

    def test_write_mark_on_zeroed_area_and_verifies(self):
        path = self.write_misc()
        r = self.sh(f'write_stay_mark "{path}"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_bytes(path)[OFFSET:OFFSET + 16], MARK)
        r = self.sh(f'write_stay_mark "{path}"')
        self.assertEqual(r.returncode, 0, "regravar por cima da própria marca vale")

    def test_write_refuses_area_with_other_data(self):
        path = self.write_misc(b"\x13\x37")
        r = self.sh(f'write_stay_mark "{path}"')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read_bytes(path)[OFFSET:OFFSET + 2], b"\x13\x37")
        self.assertIn("não está zerada", r.stdout)

    def test_hy300_ficar_command_marks_next_boot(self):
        path = self.write_misc()
        os.makedirs(self.path("by-name"))
        os.symlink(path, self.path("by-name/misc"))
        r = self.sh(f'sh "{FICAR}"', env={"HY300_BY_NAME": self.path("by-name")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_bytes(path)[OFFSET:OFFSET + 16], MARK)
        self.assertIn("próximo boot", r.stdout)


    # Contador de boots falhos: 16 bytes em 0x10010, "hy300-boots\0" + contagem + 3 zeros.
    def counter(self, path):
        return read_bytes(path)[COUNTER:COUNTER + 16]

    def test_boot_attempts_count_up_and_go_to_android_on_the_fourth(self):
        path = self.write_misc()
        outputs = [self.sh(f'register_boot_attempt "{path}" 3').stdout.strip() for _ in range(4)]
        self.assertEqual(outputs, ["1", "2", "3", "android"])
        self.assertEqual(self.counter(path), bytes(16), "zera ao mandar para o Android")

    def test_counter_format(self):
        path = self.write_misc()
        self.sh(f'register_boot_attempt "{path}" 3')
        self.sh(f'register_boot_attempt "{path}" 3')
        self.assertEqual(self.counter(path), b"hy300-boots\0\x02\0\0\0")

    def test_ready_clears_counter(self):
        path = self.write_misc()
        self.sh(f'register_boot_attempt "{path}" 3')
        r = self.sh(f'clear_boot_failures "{path}"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.counter(path), bytes(16))

    def test_unknown_data_in_counter_area_is_left_alone(self):
        path = self.write_misc()
        with open(path, "r+b") as f:
            f.seek(COUNTER)
            f.write(b"\x55" * 16)
        r = self.sh(f'register_boot_attempt "{path}" 3')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.counter(path), b"\x55" * 16)

    def test_mark_and_counter_do_not_overlap(self):
        path = self.write_misc(MARK)
        self.sh(f'register_boot_attempt "{path}" 3')
        data = read_bytes(path)
        self.assertEqual(data[OFFSET:OFFSET + 16], MARK)
        self.assertEqual(data[COUNTER:COUNTER + 12], b"hy300-boots\0")


make_suite(globals(), MiscMarkMixin)
