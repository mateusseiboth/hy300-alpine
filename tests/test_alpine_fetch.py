"""tools/alpine_fetch.py: cadeia de confiança do Alpine sem rodar nada do Alpine antes de conferir.

GPG do minirootfs (impressão digital fixada) -> chaves RSA do alpine-keys dentro dele ->
APKINDEX e apk-tools-static (assinatura RSA do segmento de controle e datahash do segmento de
dados) -> apk.static, que confere o resto.

Os pacotes de teste são montados aqui com uma chave RSA gerada pelo openssl.

Rodar: python3 -I -m unittest discover -s tests
"""
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import alpine_fetch  # noqa: E402

KEY_NAME = "test@example.org-1234.rsa.pub"
SHA1_PREFIX = bytes.fromhex("3021300906052b0e03021a05000414")


def build_tar_gz(files, end=True):
    """tar.gz em memória. end=False corta os blocos finais, como o apk faz na assinatura e no controle."""
    buf = io.BytesIO()
    tar = tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT)
    for name, data in files.items():
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()[:tar.offset]
    if end:
        tar.close()
        raw = buf.getvalue()
    return gzip.compress(raw, mtime=0)


def read_private_numbers(path):
    text = subprocess.run(["openssl", "rsa", "-in", path, "-noout", "-text"], capture_output=True,
                          text=True, check=True).stdout

    def read_field(name):
        block = re.search(name + r":\s*\n((?:\s+[0-9a-f:]+\n)+)", text).group(1)
        return int(re.sub(r"[\s:]", "", block), 16)
    return read_field("modulus"), read_field("privateExponent")


def sign_sha1(numbers, data):
    n, d = numbers
    k = (n.bit_length() + 7) // 8
    digest_info = SHA1_PREFIX + hashlib.sha1(data).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(digest_info) - 3) + b"\x00" + digest_info
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


@unittest.skipUnless(shutil.which("openssl"), "sem openssl no host")
class ApkSignatureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hy300-apk-")
        key = os.path.join(cls.tmp, "key.pem")
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], capture_output=True, check=True)
        cls.keys = os.path.join(cls.tmp, "keys")
        os.makedirs(cls.keys)
        subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-out", os.path.join(cls.keys, KEY_NAME)],
                       capture_output=True, check=True)
        cls.numbers = read_private_numbers(key)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def build_apk(self, data_files, tamper_data=False, key_name=KEY_NAME):
        data = build_tar_gz(data_files)
        pkginfo = f"pkgname = apk-tools-static\npkgver = 3.0.9-r0\ndatahash = {hashlib.sha256(data).hexdigest()}\n"
        control = build_tar_gz({".PKGINFO": pkginfo.encode()}, end=False)
        signature = build_tar_gz({f".SIGN.RSA.{key_name}": sign_sha1(self.numbers, control)}, end=False)
        data = build_tar_gz({"sbin/apk.static": b"OUTRO"}) if tamper_data else data
        return signature + control + data

    def test_valid_apk(self):
        apk = self.build_apk({"sbin/apk.static": b"\x7fELF binario"})
        info = alpine_fetch.verify_apk(apk, self.keys)
        self.assertEqual(info["pkgver"], "3.0.9-r0")
        files = alpine_fetch.read_apk_data(apk)
        self.assertEqual(files["sbin/apk.static"], b"\x7fELF binario")

    def test_tampered_data_fails(self):
        apk = self.build_apk({"sbin/apk.static": b"x"}, tamper_data=True)
        with self.assertRaisesRegex(alpine_fetch.VerifyError, "datahash"):
            alpine_fetch.verify_apk(apk, self.keys)

    def test_tampered_control_fails(self):
        apk = bytearray(self.build_apk({"sbin/apk.static": b"x"}))
        streams = alpine_fetch.split_gzip_streams(bytes(apk))
        control = gzip.compress(gzip.decompress(streams[1]).replace(b"3.0.9", b"9.9.9"), mtime=0)
        with self.assertRaisesRegex(alpine_fetch.VerifyError, "assinatura"):
            alpine_fetch.verify_apk(streams[0] + control + streams[2], self.keys)

    def test_unknown_key_fails(self):
        apk = self.build_apk({"x": b"x"}, key_name="outra@example.org-9999.rsa.pub")
        with self.assertRaisesRegex(alpine_fetch.VerifyError, "chave"):
            alpine_fetch.verify_apk(apk, self.keys)

    def test_signed_index_and_package_lookup(self):
        index_text = b"C:Q1abc=\nP:apk-tools-static\nV:3.0.9-r0\n\nP:busybox\nV:1.37.0-r31\n\n"
        content = build_tar_gz({"DESCRIPTION": b"v3.24", "APKINDEX": index_text})
        signature = build_tar_gz({f".SIGN.RSA.{KEY_NAME}": sign_sha1(self.numbers, content)}, end=False)
        text = alpine_fetch.verify_index(signature + content, self.keys)
        self.assertEqual(alpine_fetch.find_package_version(text, "apk-tools-static"), "3.0.9-r0")
        with self.assertRaises(alpine_fetch.VerifyError):
            alpine_fetch.verify_index(signature + build_tar_gz({"APKINDEX": b"P:x\n"}), self.keys)


@unittest.skipUnless(shutil.which("gpg"), "sem gpg no host")
class GpgTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hy300-gpg-")
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, mode=0o700)
        gpg = ["gpg", "--homedir", home, "--batch", "--quiet"]
        subprocess.run(gpg + ["--passphrase", "", "--quick-gen-key", "teste@example.org", "ed25519", "sign", "never"],
                       capture_output=True, check=True)
        self.fpr = re.search(r"^fpr:+([0-9A-F]+):", subprocess.run(gpg + ["--with-colons", "--fingerprint"],
                             capture_output=True, text=True).stdout, re.M).group(1)
        self.key = os.path.join(self.tmp, "key.asc")
        subprocess.run(gpg + ["--armor", "--export", "-o", self.key], check=True)
        self.file = os.path.join(self.tmp, "rootfs.tar.gz")
        with open(self.file, "wb") as f:
            f.write(b"conteudo")
        subprocess.run(gpg + ["--armor", "--detach-sign", "-o", self.file + ".asc", self.file], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_valid_signature_with_pinned_fingerprint(self):
        alpine_fetch.verify_gpg(self.file, self.file + ".asc", self.key, self.fpr)

    def test_wrong_fingerprint_fails(self):
        with self.assertRaises(alpine_fetch.VerifyError):
            alpine_fetch.verify_gpg(self.file, self.file + ".asc", self.key, "0" * 40)

    def test_tampered_file_fails(self):
        with open(self.file, "ab") as f:
            f.write(b"x")
        with self.assertRaises(alpine_fetch.VerifyError):
            alpine_fetch.verify_gpg(self.file, self.file + ".asc", self.key, self.fpr)


if __name__ == "__main__":
    unittest.main()
