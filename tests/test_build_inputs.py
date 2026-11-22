"""tools/build_inputs.py: o que o build lê do PC e confere antes de montar a imagem.

Rodar: python3 -I -m unittest discover -s tests
"""
import base64
import os
import shutil
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import build_inputs  # noqa: E402

CREDENTIALS = ("WIFI_SSID=Casa\nWIFI_PSK=senha-de-casa\nWIFI_ADDRESS=192.0.2.10/24\n"
               "WIFI_GATEWAY=192.0.2.1\nWIFI_DNS=192.0.2.1\n")


def build_key_line(key_type="ssh-rsa", blob_type=None, comment="eu@pc"):
    name = (blob_type or key_type).encode()
    blob = struct.pack(">I", len(name)) + name + b"\x00\x00\x00\x01\x23"
    return f"{key_type} {base64.b64encode(blob).decode()} {comment}\n"


class BuildInputsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hy300-inputs-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, text, mode=0o644):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def test_public_key_valid(self):
        path = self.write("id_rsa.pub", build_key_line())
        self.assertTrue(build_inputs.read_public_key(path).startswith("ssh-rsa AAAA"))

    def test_public_key_missing_or_broken(self):
        with self.assertRaisesRegex(build_inputs.InputError, "não existe"):
            build_inputs.read_public_key(os.path.join(self.tmp, "nada.pub"))
        for text in ("", "ssh-rsa naoebase64!\n", build_key_line(blob_type="ssh-ed25519"),
                     build_key_line() + build_key_line(), "-----BEGIN OPENSSH PRIVATE KEY-----\n"):
            path = self.write("k.pub", text)
            with self.assertRaises(build_inputs.InputError, msg=text):
                build_inputs.read_public_key(path)

    def test_kconfig_reports_missing_and_wrong(self):
        config = self.write(".config", "CONFIG_OVERLAY_FS=y\nCONFIG_DRM_PANFROST=y\n# CONFIG_KEXEC is not set\n")
        required = self.write("req", "# comentário\nCONFIG_OVERLAY_FS=y\nCONFIG_DRM_PANFROST=m\nCONFIG_KEXEC=y\nCONFIG_F2FS_FS=y\n")
        problems = build_inputs.check_kconfig(config, required)
        self.assertEqual(problems, ["CONFIG_DRM_PANFROST=m (está =y)", "CONFIG_KEXEC=y (está desligado)",
                                    "CONFIG_F2FS_FS=y (está desligado)"])

    def test_prune_removes_only_listed_package_files(self):
        root = os.path.join(self.tmp, "root")
        db = ("P:python3\nV:3.14\nF:usr/bin\nR:python3\nR:python3.14\nF:usr/lib/python3.14\nR:os.py\n\n"
              "P:busybox\nV:1.37\nF:bin\nR:busybox\n\n")
        self.write("root/lib/apk/db/installed", db)
        for path in ("usr/bin/python3", "usr/bin/python3.14", "usr/lib/python3.14/os.py", "bin/busybox"):
            self.write("root/" + path, "x")
        removed = build_inputs.prune_packages(root, ["python3"])
        self.assertEqual(removed, 3)
        self.assertTrue(os.path.exists(os.path.join(root, "bin/busybox")))
        self.assertFalse(os.path.exists(os.path.join(root, "usr/lib/python3.14")))
        with self.assertRaisesRegex(build_inputs.InputError, "não instalado"):
            build_inputs.prune_packages(root, ["nao-existe"])

    def test_wpa_conf_marks_home_network(self):
        creds = self.write("credenciais.conf", CREDENTIALS, 0o600)
        text = build_inputs.build_home_wpa_conf(creds)
        self.assertIn("update_config=1", text)
        self.assertIn('id_str="casa"', text)
        self.assertIn("priority=10", text)
        self.assertIn("ssid=" + b"Casa".hex(), text)
        self.assertNotIn("senha-de-casa", text)

    def test_ap_conf_is_created_once_and_kept(self):
        path = os.path.join(self.tmp, "ap.conf")
        first = build_inputs.read_or_create_ap_conf(path)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(first["AP_SSID"], "HY300-6bot-recovery")
        self.assertEqual(len(first["AP_PASSPHRASE"]), 12)
        self.assertEqual(build_inputs.read_or_create_ap_conf(path), first)

    def test_ap_conf_rejects_bad_passphrase(self):
        path = self.write("ap.conf", "AP_SSID=HY300-6bot-recovery\nAP_PASSPHRASE=curta\n", 0o600)
        with self.assertRaises(build_inputs.InputError):
            build_inputs.read_or_create_ap_conf(path)


if __name__ == "__main__":
    unittest.main()
