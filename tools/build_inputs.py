#!/usr/bin/env python3
"""Entradas do build da recuperação que vêm do PC, conferidas antes de entrar na imagem.

Nada disto vai para o repositório (é público): a chave pública do usuário, a rede de casa,
o firmware do Wi-Fi e a senha do ponto de acesso só entram na imagem gerada em ~/hy300-work.

Subcomandos:
  pubkey ARQ                     confere a chave pública e a imprime (authorized_keys)
  kconfig .config REQUERIDAS     confere as opções obrigatórias do kernel
  prune ROOTFS PACOTE...         apaga os arquivos de pacotes do rootfs (pelo banco do apk)
  wifi --credentials C --vendor-img V --ap-conf A --out DIR
                                 rede de casa, IP fixo, firmware do AIC8800 e ponto de acesso
"""
import argparse
import base64
import os
import secrets
import shutil
import struct
import sys

HY300_RK3566 = os.environ.get("HY300_RK3566", os.path.expanduser("~/hy300-handoff/hy300-rk3566"))
sys.path.insert(0, os.path.join(HY300_RK3566, "tools"))
import wifi_payload  # noqa: E402  (hy300-rk3566: credenciais, PSK e firmware conferido por MD5)

KEY_TYPES = ("ssh-rsa", "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521")
AP_SSID = "HY300-6bot-recovery"
AP_PASSPHRASE_LENGTH = 12
# Sem 0/O, 1/l/I: a senha é lida na projeção e digitada no celular.
AP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class InputError(Exception):
    pass


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_public_key(path):
    if not os.path.isfile(path):
        raise InputError(f"{path} não existe: gere com ssh-keygen ou aponte SSH_PUBKEY para a chave pública")
    lines = [line for line in read_text(path).splitlines() if line.strip()]
    if len(lines) != 1:
        raise InputError(f"{path}: esperada uma chave pública numa linha")
    fields = lines[0].split()
    if len(fields) < 2 or fields[0] not in KEY_TYPES:
        raise InputError(f"{path}: não é uma chave pública OpenSSH ({', '.join(KEY_TYPES)})")
    try:
        blob = base64.b64decode(fields[1], validate=True)
        (length,) = struct.unpack(">I", blob[:4])
        inner = blob[4:4 + length].decode()
    except (ValueError, struct.error, UnicodeDecodeError) as error:
        raise InputError(f"{path}: chave em base64 inválida") from error
    if inner != fields[0]:
        raise InputError(f"{path}: o tipo da chave ({inner}) não confere com {fields[0]}")
    return lines[0]


def parse_kconfig(path):
    values = {}
    for line in read_text(path).splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def check_kconfig(config_path, required_path):
    current = parse_kconfig(config_path)
    problems = []
    for line in read_text(required_path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, want = line.split("=", 1)
        got = current.get(key)
        if got != want:
            problems.append(f"{line} (está {'=' + got if got else 'desligado'})")
    return problems


def read_installed_db(root):
    packages, current, directory = {}, None, ""
    for line in read_text(os.path.join(root, "lib", "apk", "db", "installed")).splitlines():
        tag, value = line[:2], line[2:]
        if tag == "P:":
            current = packages.setdefault(value, {"files": [], "dirs": []})
        elif tag == "F:" and current is not None:
            directory = value
            current["dirs"].append(value)
        elif tag == "R:" and current is not None:
            current["files"].append(os.path.join(directory, value))
    return packages


def remove_empty_dirs(root, dirs):
    for directory in sorted(set(dirs), key=len, reverse=True):
        path = os.path.join(root, directory)
        if os.path.isdir(path) and not os.path.islink(path) and not os.listdir(path):
            os.rmdir(path)


def prune_packages(root, names):
    """Apaga do rootfs os arquivos dos pacotes, pela lista do banco do apk. O banco continua
    dizendo que estão instalados (apk fix os traz de volta). Devolve quantos arquivos saíram."""
    packages = read_installed_db(root)
    removed = 0
    for name in names:
        if name not in packages:
            raise InputError(f"{name} não instalado no rootfs")
        for relative in packages[name]["files"]:
            path = os.path.join(root, relative)
            if os.path.lexists(path):
                os.remove(path)
                removed += 1
        remove_empty_dirs(root, packages[name]["dirs"])
    return removed


def build_home_wpa_conf(credentials):
    creds = wifi_payload.read_credentials(credentials)
    ssid = creds["WIFI_SSID"]
    return (
        "ctrl_interface=/var/run/wpa_supplicant\n"
        "update_config=1\n"
        "network={\n"
        f"\tssid={ssid.encode().hex()}\n"
        "\tscan_ssid=1\n"
        "\tkey_mgmt=WPA-PSK\n"
        f"\tpsk={wifi_payload.compute_psk(ssid, creds['WIFI_PSK'])}\n"
        '\tid_str="casa"\n'
        "\tpriority=10\n"
        "}\n"
    )


def write_private(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)


def parse_assignments(text):
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#"))


def read_or_create_ap_conf(path):
    """Senha do ponto de acesso: gerada no primeiro build e mantida (o usuário aprende uma vez)."""
    if not os.path.exists(path):
        passphrase = "".join(secrets.choice(AP_ALPHABET) for _ in range(AP_PASSPHRASE_LENGTH))
        write_private(path, f"AP_SSID={AP_SSID}\nAP_PASSPHRASE={passphrase}\n")
    values = parse_assignments(read_text(path))
    passphrase = values.get("AP_PASSPHRASE", "")
    if not 8 <= len(passphrase) <= 63 or not passphrase.isalnum():
        raise InputError(f"{path}: AP_PASSPHRASE precisa ter de 8 a 63 letras ou números")
    return {"AP_SSID": values.get("AP_SSID", AP_SSID), "AP_PASSPHRASE": passphrase}


def build_wifi_files(credentials, vendor_img, ap_conf, out):
    staging = os.path.join(out, ".payload")
    shutil.rmtree(staging, ignore_errors=True)
    wifi_payload.build_payload(credentials, vendor_img, staging)
    write_private(os.path.join(out, "etc", "wpa_supplicant", "wpa_supplicant.conf"), build_home_wpa_conf(credentials))
    write_private(os.path.join(out, "etc", "hy300-wifi.conf"), read_text(os.path.join(staging, "etc", "hy300-wifi.conf")))
    ap = read_or_create_ap_conf(ap_conf)
    write_private(os.path.join(out, "etc", "hy300-ap.conf"), "".join(f"{k}={v}\n" for k, v in ap.items()))
    shutil.copytree(os.path.join(staging, "lib"), os.path.join(out, "lib"), dirs_exist_ok=True)
    shutil.rmtree(staging)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pubkey").add_argument("path")
    kconfig = sub.add_parser("kconfig")
    kconfig.add_argument("config")
    kconfig.add_argument("required")
    prune = sub.add_parser("prune")
    prune.add_argument("root")
    prune.add_argument("packages", nargs="+")
    wifi = sub.add_parser("wifi")
    for name in ("--credentials", "--vendor-img", "--ap-conf", "--out"):
        wifi.add_argument(name, required=True)
    args = parser.parse_args(argv)
    try:
        return run_command(args)
    except (InputError, wifi_payload.PayloadError) as error:
        print(f"build_inputs: FALHOU: {error}", file=sys.stderr)
        return 1


def run_command(args):
    commands = {
        "pubkey": lambda: print(read_public_key(args.path)),
        "kconfig": lambda: report_kconfig(check_kconfig(args.config, args.required)),
        "prune": lambda: print(f"ok: {prune_packages(args.root, args.packages)} arquivos removidos"),
        "wifi": lambda: build_wifi_files(args.credentials, args.vendor_img, args.ap_conf, args.out),
    }
    commands[args.command]()
    return 0


def report_kconfig(problems):
    if problems:
        raise InputError("kernel sem opções da recuperação: " + "; ".join(problems))
    print("ok: opções do kernel da recuperação presentes")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
