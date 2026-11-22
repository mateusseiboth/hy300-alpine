#!/usr/bin/env python3
"""Monta um boot.img v2 do HY300 a partir de uma imagem de referência (a recovery ou a boot
de fábrica), trocando seções e acrescentando parâmetros na cmdline.

Usa o tools/mkboot.py do hy300-rk3566 (testado byte a byte contra as imagens de fábrica). A
diferença está na cmdline: ela tem 512 bytes no header v2 e a da recovery de fábrica repete
metade dos parâmetros (447 bytes). Aqui as repetições exatas saem (fica a primeira, na mesma
ordem) antes de acrescentar os parâmetros da recuperação.

Uso: mkimage.py --like REF -o SAIDA [--kernel K] [--ramdisk R] [--second S] [--dtb D]
                --append "args" [--pad-to-like]
"""
import argparse
import os
import sys

HY300_RK3566 = os.environ.get("HY300_RK3566", os.path.expanduser("~/hy300-handoff/hy300-rk3566"))
sys.path.insert(0, os.path.join(HY300_RK3566, "tools"))
import mkboot  # noqa: E402

CMDLINE_LIMIT = mkboot.FIELD_LIMITS["cmdline"]


def build_cmdline(reference, extra):
    tokens = list(dict.fromkeys(reference.split()))
    cmdline = " ".join(tokens + extra.split())
    if len(cmdline) >= CMDLINE_LIMIT:
        raise ValueError(f"cmdline com {len(cmdline)} bytes; o header v2 aceita até {CMDLINE_LIMIT - 1} (512 com o NUL)")
    return cmdline


def build_image(like, sections, extra_cmdline, pad=True):
    img = mkboot.unpack(like)
    img = mkboot.replace(img, **sections)
    img = mkboot.replace(img, cmdline=build_cmdline(img.cmdline.decode(), extra_cmdline).encode())
    return mkboot.build(img, pad_to=len(like) if pad else None)


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--like", required=True)
    parser.add_argument("-o", "--output", required=True)
    for section in mkboot.SECTIONS:
        parser.add_argument(f"--{section.replace('_', '-')}", dest=section)
    parser.add_argument("--append", default="")
    parser.add_argument("--pad-to-like", action="store_true")
    args = parser.parse_args(argv)
    sections = {s: read_file(getattr(args, s)) for s in mkboot.SECTIONS if getattr(args, s)}
    try:
        data = build_image(read_file(args.like), sections, args.append, args.pad_to_like)
    except ValueError as error:
        print(f"mkimage: FALHOU: {error}", file=sys.stderr)
        return 1
    with open(args.output, "wb") as f:
        f.write(data)
    print(f"ok {args.output}: {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
