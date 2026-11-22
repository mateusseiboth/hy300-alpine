"""scripts/flash-backup-from-android.sh: grava a imagem da partição backup a partir do Android
de fábrica (adb push + dd), como o flash-test-recovery.sh do hy300-rk3566.

Só grava se a backup estiver toda zerada (como de fábrica) ou tiver uma imagem nossa já
registrada. O adb é falso: "partições" e /data/local/tmp são arquivos num diretório.

Rodar: python3 -I -m unittest discover -s tests
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "flash-backup-from-android.sh")
PART_SIZE = 1024 * 1024

FAKE_ADB = r"""#!/bin/bash
# adb falso: "shell" roda o comando no sh do host com /dev/block/by-name e /data/local/tmp
# trocados por diretórios do teste.
echo "adb $*" >>"$FAKE_DIR/adb.log"
case "$1" in
root|wait-for-device) exit 0 ;;
push) cp "$2" "$FAKE_DIR/data${3}"; exit $? ;;
shell) shift
	cmd="$*"
	cmd="${cmd//\/dev\/block\/by-name/$FAKE_DIR/by-name}"
	cmd="${cmd//\/data\/local\/tmp/$FAKE_DIR/data/data/local/tmp}"
	cmd="${cmd//blockdev --getsize64/stat -c %s}"
	sh -c "$cmd" ;;
esac
"""


class FlashBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hy300-flash-backup-")
        for d in ("by-name", "data/data/local/tmp", "bin", "work"):
            os.makedirs(os.path.join(self.tmp, d))
        adb = os.path.join(self.tmp, "bin", "adb")
        with open(adb, "w") as f:
            f.write(FAKE_ADB)
        os.chmod(adb, 0o755)
        self.part = os.path.join(self.tmp, "by-name", "backup")
        self.write_part(bytes(PART_SIZE))
        self.img = os.path.join(self.tmp, "backup-alpine.img")
        with open(self.img, "wb") as f:
            f.write(os.urandom(PART_SIZE))
        self.known = os.path.join(self.tmp, "work", "backup-gravadas.txt")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_part(self, data):
        with open(self.part, "wb") as f:
            f.write(data)

    def read_part(self):
        with open(self.part, "rb") as f:
            return f.read()

    def run_script(self, *args):
        env = dict(os.environ, PATH=os.path.join(self.tmp, "bin") + ":" + os.environ["PATH"], FAKE_DIR=self.tmp,
                   HY300_BACKUP_KNOWN=self.known)
        return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True, timeout=60)

    def test_writes_over_zeroed_partition_and_registers_hash(self):
        r = self.run_script(self.img)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.img, "rb") as f:
            self.assertEqual(self.read_part(), f.read())
        digest = hashlib.sha256(self.read_part()).hexdigest()
        self.assertIn(digest, open(self.known).read())
        self.assertEqual(os.listdir(os.path.join(self.tmp, "data/data/local/tmp")), [])

    def test_refuses_unknown_content(self):
        self.write_part(b"\x01" * PART_SIZE)
        r = self.run_script(self.img)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.read_part(), b"\x01" * PART_SIZE)
        self.assertIn("não está zerada", r.stdout)

    def test_accepts_registered_image(self):
        old = os.urandom(PART_SIZE)
        self.write_part(old)
        with open(self.known, "w") as f:
            f.write(hashlib.sha256(old).hexdigest() + "\n")
        r = self.run_script(self.img)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_refuses_image_bigger_than_partition(self):
        with open(self.img, "wb") as f:
            f.write(bytes(PART_SIZE + 512))
        r = self.run_script(self.img)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("maior", r.stdout)


if __name__ == "__main__":
    unittest.main()
