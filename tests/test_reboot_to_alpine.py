"""scripts/reboot-to-alpine.sh: do Android (adb) para o Alpine, ficando lá sem teclado.

Grava a marca de "ficar" na misc (0x10000, só se a área estiver zerada ou já com a marca),
confere lendo de volta e reinicia para onde o Alpine estiver: na boot, reboot normal; na
recovery, o reboot-to-test-slot.sh do hy300-rk3566 (registrador, sem BCB). O lugar sai do
cabeçalho da boot/recovery (hy300.slot=...) ou de --alpine-in. O adb é falso.

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "reboot-to-alpine.sh")
OFFSET = 0x10000
MARK = b"hy300-ficar\0\x01\0\0\0"

FAKE_ADB = r"""#!/bin/bash
echo "adb $*" >>"$FAKE_DIR/adb.log"
case "$1" in
root|wait-for-device) exit 0 ;;
push) cp "$2" "$FAKE_DIR/data${3}"; exit $? ;;
shell) shift
	cmd="$*"
	[ "$cmd" = reboot ] && { echo reboot >>"$FAKE_DIR/rebooted"; exit 0; }
	cmd="${cmd//\/dev\/block\/by-name/$FAKE_DIR/by-name}"
	cmd="${cmd//\/data\/local\/tmp/$FAKE_DIR/data/data/local/tmp}"
	sh -c "$cmd" ;;
esac
"""


def build_bootimg_header(cmdline):
    header = bytearray(4096)
    header[:8] = b"ANDROID!"
    header[64:64 + len(cmdline)] = cmdline
    return bytes(header)


class RebootToAlpineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hy300-r2a-")
        for d in ("by-name", "data/data/local/tmp", "bin"):
            os.makedirs(os.path.join(self.tmp, d))
        self.write_bin("adb", FAKE_ADB)
        self.write_bin("slot", '#!/bin/sh\necho "slot TEST_IMAGE=$TEST_IMAGE" >>"$FAKE_DIR/rebooted"\n')
        self.misc = os.path.join(self.tmp, "by-name", "misc")
        self.write_part("misc", bytes(4 * 1024 * 1024))
        self.write_part("boot", build_bootimg_header(b"console=ttyFIQ0 androidboot.hardware=rk30board"))
        self.write_part("recovery", build_bootimg_header(b"console=ttyFIQ0 hy300.slot=recovery hy300.autoboot=5"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_bin(self, name, text):
        path = os.path.join(self.tmp, "bin", name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def write_part(self, name, data):
        with open(os.path.join(self.tmp, "by-name", name), "wb") as f:
            f.write(data)

    def read_mark_area(self):
        with open(self.misc, "rb") as f:
            f.seek(OFFSET)
            return f.read(16)

    def rebooted(self):
        path = os.path.join(self.tmp, "rebooted")
        return open(path).read() if os.path.exists(path) else ""

    def run_script(self, *args):
        env = dict(os.environ, PATH=os.path.join(self.tmp, "bin") + ":" + os.environ["PATH"], FAKE_DIR=self.tmp, HY300_ADB_ROOT_WAIT="0",
                   HY300_REBOOT_TO_TEST_SLOT=os.path.join(self.tmp, "bin", "slot"),
                   HY300_RECOVERY_IMAGE="/imagens/recovery-alpine.img")
        return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True, timeout=60)

    def test_alpine_in_recovery_marks_and_uses_the_register_path(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_mark_area(), MARK)
        self.assertIn("slot TEST_IMAGE=/imagens/recovery-alpine.img", self.rebooted())
        self.assertEqual(os.listdir(os.path.join(self.tmp, "data/data/local/tmp")), [])

    def test_alpine_in_boot_uses_normal_reboot(self):
        self.write_part("boot", build_bootimg_header(b"console=ttyFIQ0 hy300.slot=boot hy300.autoboot=5"))
        self.write_part("recovery", build_bootimg_header(b"console=ttyFIQ0 androidboot.hardware=rk30board"))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.rebooted().strip(), "reboot")

    def test_explicit_place_wins(self):
        r = self.run_script("--alpine-in", "boot")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.rebooted().strip(), "reboot")

    def test_refuses_area_with_other_data(self):
        with open(self.misc, "r+b") as f:
            f.seek(OFFSET)
            f.write(b"\x42" * 4)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.rebooted(), "")
        self.assertIn("não está zerada", r.stdout)

    def test_existing_mark_is_accepted(self):
        with open(self.misc, "r+b") as f:
            f.seek(OFFSET)
            f.write(MARK)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_without_alpine_anywhere_fails(self):
        self.write_part("recovery", build_bootimg_header(b"console=ttyFIQ0"))
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.read_mark_area(), bytes(16))

    def test_dry_run_writes_and_reboots_nothing(self):
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_mark_area(), bytes(16))
        self.assertEqual(self.rebooted(), "")


if __name__ == "__main__":
    unittest.main()
