"""Base dos testes das funções em shell do rootfs (rootfs/usr/lib/hy300/*.sh).

Cada teste roda num diretório temporário, com comandos falsos (insmod, ip, kexec, reboot...)
que gravam os argumentos em FAKE_LOG. Os testes rodam no /bin/sh do host e, se houver o
busybox estático do Alpine (do rootfs gerado pelo build.sh) e o binfmt do qemu-aarch64, no
busybox também, com um PATH que só tem os applets dele: é o shell que roda no aparelho.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LIB_DIR = os.path.join(REPO, "rootfs", "usr", "lib", "hy300")
ROOTFS = os.environ.get("HY300_ALPINE_ROOTFS", "/mnt/hd/hy300-alpine/build/rootfs")
BUSYBOX = os.path.join(ROOTFS, "bin", "busybox.static")
BINFMT = "/proc/sys/fs/binfmt_misc/qemu-aarch64"

FAKE = """#!/bin/sh
echo "$(basename "$0") $*" >>"$FAKE_LOG"
case "$(basename "$0") $*" in
{cases}
esac
exit 0
"""


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def build_applet_dir(busybox, dest):
    os.makedirs(dest, exist_ok=True)
    applets = subprocess.run([busybox, "--list"], capture_output=True, text=True, check=True).stdout.split()
    for applet in applets:
        link = os.path.join(dest, applet)
        if not os.path.lexists(link):
            os.symlink(busybox, link)
    return dest


class Runner:
    def __init__(self, argv, path=None):
        self.argv = argv
        self.path = path

    def run(self, script, tmp, fake_bin, libs, env=None, stdin=None):
        sources = "; ".join(f'. "{os.path.join(LIB_DIR, lib)}"' for lib in libs)
        path = fake_bin + ":" + (self.path or os.environ["PATH"])
        full_env = {"PATH": path, "FAKE_LOG": os.path.join(tmp, "fake.log"), "LANG": "C",
                    "HY300_LIB": LIB_DIR, "HY300_RUN": os.path.join(tmp, "run"),
                    "KMSG": os.path.join(tmp, "kmsg"), "HY300_TTY": os.path.join(tmp, "tty1")}
        full_env.update(env or {})
        data = stdin.encode() if isinstance(stdin, str) else stdin
        r = subprocess.run(self.argv + ["-c", f"{sources}; {script}"], cwd=tmp, env=full_env,
                           capture_output=True, input=data, timeout=60)
        return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode(errors="replace"),
                                           r.stderr.decode(errors="replace"))


def build_runners():
    runners = {"host": Runner(["/bin/sh"])}
    if os.path.isfile(BUSYBOX) and os.path.isfile(BINFMT):
        applets = build_applet_dir(BUSYBOX, os.path.join(tempfile.gettempdir(), "hy300-alpine-applets"))
        runners["busybox"] = Runner([BUSYBOX, "sh"], applets)
    return runners


class ShellMixin:
    """Usar com unittest.TestCase; a classe concreta define `runner` e `libs`."""
    runner = None
    libs = ("common.sh",)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hy300-alpine-sh-")
        self.bin = os.path.join(self.tmp, "fake-bin")
        os.makedirs(self.bin)
        os.makedirs(os.path.join(self.tmp, "run"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fake(self, name, cases=""):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(FAKE.format(cases=cases))
        os.chmod(path, 0o755)

    def write(self, name, data, mode=None):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if isinstance(data, bytes) else "w") as f:
            f.write(data)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def path(self, name):
        return os.path.join(self.tmp, name)

    def sh(self, script, env=None, stdin=None):
        return self.runner.run(script, self.tmp, self.bin, self.libs, env, stdin)

    def fake_log(self):
        path = os.path.join(self.tmp, "fake.log")
        return read_text(path).splitlines() if os.path.exists(path) else []

    def kmsg(self):
        path = os.path.join(self.tmp, "kmsg")
        return read_text(path) if os.path.exists(path) else ""


def make_suite(module_globals, mixin):
    """Cria uma classe de teste por shell disponível (host, busybox)."""
    for name, runner in build_runners().items():
        cls_name = f"{mixin.__name__.replace('Mixin', '')}_{name}"
        module_globals[cls_name] = type(cls_name, (mixin, unittest.TestCase), {"runner": runner})
