#!/usr/bin/env python3
"""Baixa o minirootfs e o apk.static do Alpine conferindo a cadeia de confiança inteira.

1. minirootfs aarch64: SHA-256 publicado e assinatura GPG do Natanael Copa, cuja impressão
   digital está fixada aqui (a chave vem de alpinelinux.org/keys);
2. as chaves RSA do Alpine para x86_64 saem do alpine-keys dentro do minirootfs conferido;
3. o APKINDEX x86_64 (assinado) diz a versão do apk-tools-static; o .apk é conferido pela
   assinatura RSA do segmento de controle e pelo datahash do segmento de dados;
4. o apk.static confere sozinho todos os pacotes aarch64 com as chaves do minirootfs.

Nada do Alpine roda antes de ser conferido. A verificação RSA (PKCS#1 v1.5) é feita aqui em
Python puro: o Alpine ainda assina com SHA-1, que o OpenSSL do Fedora recusa por política.

Uso: alpine_fetch.py bootstrap --version 3.24.4 --out DIR
     (DIR/alpine-minirootfs-<v>-aarch64.tar.gz e DIR/apk.static, já conferidos)
"""
import argparse
import base64
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
import urllib.request
import zlib

MIRROR = "https://dl-cdn.alpinelinux.org/alpine"
NCOPA_KEY_URL = "https://alpinelinux.org/keys/ncopa.asc"
NCOPA_FINGERPRINT = "0482D84022F52DF1C4E7CD43293ACD0907D9495A"
HASH_PREFIXES = {
    "sha1": bytes.fromhex("3021300906052b0e03021a05000414"),
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
}


class VerifyError(Exception):
    pass


def split_gzip_streams(data):
    streams, offset = [], 0
    while offset < len(data):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        decoder.decompress(data[offset:])
        used = len(data) - offset - len(decoder.unused_data)
        streams.append(data[offset:offset + used])
        offset += used
    return streams


def read_tar_members(stream):
    members = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(stream))) as tar:
        for info in tar:
            if info.isfile():
                members[info.name] = tar.extractfile(info).read()
    return members


def read_der(data, offset):
    """(tag, conteúdo, próximo offset) de um elemento DER."""
    tag, length = data[offset], data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7f
        length = int.from_bytes(data[offset:offset + count], "big")
        offset += count
    return tag, data[offset:offset + length], offset + length


def parse_public_key(pem):
    """(n, e) de uma chave pública RSA em PEM (SubjectPublicKeyInfo)."""
    body = "".join(line for line in pem.strip().splitlines() if not line.startswith("-----"))
    der = base64.b64decode(body)
    _, spki, _ = read_der(der, 0)
    _, _, offset = read_der(spki, 0)
    _, bitstring, _ = read_der(spki, offset)
    _, rsa, _ = read_der(bitstring[1:], 0)
    _, n, offset = read_der(rsa, 0)
    _, e, _ = read_der(rsa, offset)
    return int.from_bytes(n, "big"), int.from_bytes(e, "big")


def is_valid_rsa_signature(pem, signature, data, hash_name):
    n, e = parse_public_key(pem)
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    digest_info = HASH_PREFIXES[hash_name] + hashlib.new(hash_name, data).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(digest_info) - 3) + b"\x00" + digest_info
    return em == expected


def read_signature(members):
    for name, data in members.items():
        match = re.fullmatch(r"\.SIGN\.RSA(256)?\.(.+)", name)
        if match:
            return ("sha256" if match.group(1) else "sha1"), match.group(2), data
    raise VerifyError("segmento de assinatura sem .SIGN.RSA")


def require_signed(signature_stream, signed_stream, keys_dir):
    hash_name, key_name, signature = read_signature(read_tar_members(signature_stream))
    key_path = os.path.join(keys_dir, key_name)
    if os.path.basename(key_name) != key_name or not os.path.isfile(key_path):
        raise VerifyError(f"chave {key_name} não está em {keys_dir}")
    with open(key_path) as f:
        pem = f.read()
    if not is_valid_rsa_signature(pem, signature, signed_stream, hash_name):
        raise VerifyError(f"assinatura RSA inválida (chave {key_name})")


def parse_pkginfo(text):
    info = {}
    for line in text.splitlines():
        key, sep, value = line.partition(" = ")
        if sep:
            info[key] = value
    return info


def verify_apk(data, keys_dir):
    """Confere assinatura e datahash de um .apk (formato v2); devolve o .PKGINFO."""
    streams = split_gzip_streams(data)
    if len(streams) != 3:
        raise VerifyError(f"esperados 3 segmentos gzip, há {len(streams)}")
    require_signed(streams[0], streams[1], keys_dir)
    info = parse_pkginfo(read_tar_members(streams[1])[".PKGINFO"].decode())
    if info.get("datahash") != hashlib.sha256(streams[2]).hexdigest():
        raise VerifyError("datahash não confere com o segmento de dados")
    return info


def read_apk_data(data):
    return read_tar_members(split_gzip_streams(data)[2])


def verify_index(data, keys_dir):
    """Confere a assinatura do APKINDEX.tar.gz; devolve o texto do APKINDEX."""
    streams = split_gzip_streams(data)
    if len(streams) != 2:
        raise VerifyError(f"APKINDEX com {len(streams)} segmentos gzip, esperados 2")
    require_signed(streams[0], streams[1], keys_dir)
    return read_tar_members(streams[1])["APKINDEX"].decode()


def find_package_version(index_text, name):
    for block in index_text.split("\n\n"):
        fields = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        if fields.get("P") == name:
            return fields["V"]
    raise VerifyError(f"{name} não está no APKINDEX")


def verify_gpg(path, signature, key_file, fingerprint):
    home = tempfile.mkdtemp(prefix="hy300-gpg-")
    try:
        gpg = ["gpg", "--homedir", home, "--batch", "--quiet"]
        subprocess.run(gpg + ["--import", key_file], capture_output=True, check=True)
        r = subprocess.run(gpg + ["--status-fd", "1", "--verify", signature, path], capture_output=True, text=True)
        valid = re.findall(r"^\[GNUPG:\] VALIDSIG \S+ .* ([0-9A-F]{40})$", r.stdout, re.M)
        if r.returncode != 0 or fingerprint.upper() not in valid:
            raise VerifyError(f"assinatura GPG de {os.path.basename(path)} inválida ou de outra chave")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def download(url, dest):
    if not os.path.isfile(dest):
        with urllib.request.urlopen(url, timeout=60) as r, open(dest + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(dest + ".part", dest)
    return dest


def read_file(path, mode="rb"):
    with open(path, mode) as f:
        return f.read()


def require_sha256(path, sha_file):
    want = read_file(sha_file, "r").split()[0]
    got = hashlib.sha256(read_file(path)).hexdigest()
    if want != got:
        raise VerifyError(f"SHA-256 de {os.path.basename(path)}: {got}, publicado {want}")


def fetch_minirootfs(version, out):
    branch = "v" + ".".join(version.split(".")[:2])
    name = f"alpine-minirootfs-{version}-aarch64.tar.gz"
    base = f"{MIRROR}/{branch}/releases/aarch64/{name}"
    path = download(base, os.path.join(out, name))
    download(base + ".sha256", path + ".sha256")
    download(base + ".asc", path + ".asc")
    key = download(NCOPA_KEY_URL, os.path.join(out, "ncopa.asc"))
    require_sha256(path, path + ".sha256")
    verify_gpg(path, path + ".asc", key, NCOPA_FINGERPRINT)
    return path, branch


def extract_x86_keys(minirootfs, dest):
    os.makedirs(dest, exist_ok=True)
    prefix = "./usr/share/apk/keys/x86_64/"
    with tarfile.open(minirootfs) as tar:
        for info in tar:
            if info.name.startswith(prefix) and info.name.endswith(".pub"):
                target = os.path.join(dest, os.path.basename(info.name))
                member = tar.extractfile(info) or tar.extractfile(tar.getmember(info.linkname))
                with open(target, "wb") as f:
                    f.write(member.read())
    if not os.listdir(dest):
        raise VerifyError("minirootfs sem as chaves x86_64 do alpine-keys")
    return dest


def fetch_apk_static(branch, keys, out):
    repo = f"{MIRROR}/{branch}/main/x86_64"
    index = download(f"{repo}/APKINDEX.tar.gz", os.path.join(out, "APKINDEX-x86_64.tar.gz"))
    version = find_package_version(verify_index(read_file(index), keys), "apk-tools-static")
    name = f"apk-tools-static-{version}.apk"
    apk = read_file(download(f"{repo}/{name}", os.path.join(out, name)))
    verify_apk(apk, keys)
    binary = os.path.join(out, "apk.static")
    with open(binary, "wb") as f:
        f.write(read_apk_data(apk)["sbin/apk.static"])
    os.chmod(binary, 0o755)
    return binary, version


def run_bootstrap(args):
    os.makedirs(args.out, exist_ok=True)
    minirootfs, branch = fetch_minirootfs(args.version, args.out)
    keys = extract_x86_keys(minirootfs, os.path.join(args.out, "keys-x86_64"))
    binary, version = fetch_apk_static(branch, keys, args.out)
    print(f"ok: {os.path.basename(minirootfs)} (GPG {NCOPA_FINGERPRINT[-16:]}), apk-tools-static {version}")
    print(f"minirootfs={minirootfs}")
    print(f"apk_static={binary}")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap")
    boot.add_argument("--version", required=True)
    boot.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        return run_bootstrap(args)
    except VerifyError as error:
        print(f"alpine_fetch: FALHOU: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
