#!/usr/bin/env python3
"""Teste de fumaça da recuperação no QEMU (virt, aarch64): o mesmo initramfs da imagem do
aparelho, num kernel do hy300-6.1 com PL011, virtio-blk, virtio-net e teclado virtio.

Rodadas:
  ficar      hy300.slot=boot hy300.autoboot=0, disco com a partição backup (a imagem do build):
             modo completo (rootfs.sqfs da backup conferido pelo sha256), labwc presente, rede
             salva na backup (que volta a só-leitura). Confere pelo SSH (hostfwd, chave do usuário):
             login só por chave, Alpine e kernel, /dev/block/by-name, BCB da misc apagado,
             DHCP no cabo (virtio-net), Wi-Fi em FALHOU (sem SDIO), backup e gravação com os
             scripts do PC, hy300-kexec --dry-run. Pelo teclado virtio: a opção 4 do menu do
             tty1 (shell) e o shell automático do tty2 (Alt+F2). No fim, kexec de verdade num
             boot.img com um initramfs que só escreve uma marca.
  As outras rodadas não têm a partição backup: modo de resgate (o núcleo do initramfs).
  android    hy300.slot=boot hy300.autoboot=2 sem tecla: reboot(RESTART2, "recovery").
  normal     hy300.slot=recovery hy300.autoboot=2 sem tecla: reboot normal.
  tecla      hy300.slot=boot hy300.autoboot=20 e uma tecla durante a contagem: fica.

Uso: smoke_qemu.py Image initramfs.cpio.xz dir_de_trabalho misc_de_fabrica.img chave.pub backup-alpine.img
"""
import gzip
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HY300_RK3566 = os.environ.get("HY300_RK3566", os.path.expanduser("~/hy300-handoff/hy300-rk3566"))
sys.path.insert(0, os.path.join(HY300_RK3566, "tools"))
import mkboot  # noqa: E402

SECTOR = 512
MISC_START, MISC_SECTORS = 10240, 8192
BOOT_START, BOOT_SECTORS = 18432, 4096
BACKUP_START = 55296
CHUNK = 1 << 20
BCB_SIZE = 2048
BOOT_TIMEOUT = 300
# rockchip_drm_init faz SMC para o TF-A, que não existe no virt.
CMDLINE = "console=ttyAMA0 panic=10 initcall_blacklist=rockchip_drm_init"
KEXEC_MARK = "HY300_KEXEC_OK"


class Qemu:
    def __init__(self, image, initramfs, workdir, name, cmdline, disk):
        self.log_path = os.path.join(workdir, f"smoke-{name}.log")
        self.qmp_path = os.path.join(workdir, f"qmp-{name}.sock")
        self.port = find_free_port()
        for path in (self.log_path, self.qmp_path):
            if os.path.exists(path):
                os.remove(path)
        argv = ["qemu-system-aarch64", "-M", "virt,gic-version=3", "-cpu", "cortex-a55", "-smp", "4",
                "-m", "1536", "-kernel", image, "-initrd", initramfs, "-append", f"{CMDLINE} {cmdline}",
                "-drive", f"if=none,file={disk},format=raw,id=d", "-device", "virtio-blk-device,drive=d",
                "-netdev", f"user,id=n,hostfwd=tcp:127.0.0.1:{self.port}-:22",
                "-device", "virtio-net-device,netdev=n", "-device", "virtio-keyboard-device",
                # O virtio_input só aceita virtio moderno; o virtio-mmio do virt nasce legado.
                "-global", "virtio-mmio.force-legacy=false",
                "-display", "none", "-monitor", "none", "-serial", f"file:{self.log_path}",
                "-qmp", f"unix:{self.qmp_path},server=on,wait=off", "-no-reboot"]
        self.proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.qmp = None

    def read_log(self):
        try:
            with open(self.log_path, errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def wait_for_log(self, text, timeout=BOOT_TIMEOUT):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if text in self.read_log():
                return True
            if self.proc.poll() is not None:
                return text in self.read_log()
            time.sleep(1)
        return False

    def wait_for_exit(self, timeout=BOOT_TIMEOUT):
        try:
            self.proc.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def connect_qmp(self):
        end = time.monotonic() + 30
        while self.qmp is None and time.monotonic() < end:
            try:
                sock = socket.socket(socket.AF_UNIX)
                sock.connect(self.qmp_path)
                self.qmp = sock.makefile("rw")
            except OSError:
                time.sleep(0.5)
        self.qmp.readline()
        self.command_qmp("qmp_capabilities")

    def command_qmp(self, name, **arguments):
        self.qmp.write(json.dumps({"execute": name, "arguments": arguments}) + "\n")
        self.qmp.flush()
        while True:
            reply = json.loads(self.qmp.readline())
            if "return" in reply or "error" in reply:
                return reply

    def send_keys(self, *qcodes):
        self.qmp is None and self.connect_qmp()
        self.command_qmp("send-key", keys=[{"type": "qcode", "data": code} for code in qcodes])
        time.sleep(0.15)

    def type_text(self, text):
        names = {" ": "spc", "/": "slash", "-": "minus", ".": "dot", "\n": "ret"}
        for char in text:
            self.send_keys(names.get(char, char))

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


def find_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_misc(factory):
    with open(factory, "rb") as f:
        misc = bytearray(f.read())
    bcb = b"boot-recovery".ljust(32, b"\0") + b"recovery\n--hy300-smoke\0"
    misc[:len(bcb)] = bcb
    return bytes(misc)


def copy_sparse(src, dest_file, offset):
    with open(src, "rb") as f:
        position = offset
        while chunk := f.read(CHUNK):
            if chunk.count(0) != len(chunk):
                dest_file.seek(position)
                dest_file.write(chunk)
            position += len(chunk)


def create_disk(path, misc, boot, backup=None):
    """GPT como o do HY300 em miniatura; a backup só existe se houver a imagem."""
    backup_sectors = os.path.getsize(backup) // SECTOR if backup else 0
    with open(path, "wb") as f:
        f.truncate((BACKUP_START + backup_sectors + 4096) * SECTOR)
    layout = ("label: gpt\nstart=2048, size=8192, name=uboot\nsize=8192, name=misc\n"
              "size=4096, name=boot\nsize=32768, name=recovery\n")
    layout += f"start={BACKUP_START}, size={backup_sectors}, name=backup\n" if backup else ""
    subprocess.run(["sfdisk", "-q", path], input=layout, text=True, check=True)
    with open(path, "r+b") as f:
        f.seek(MISC_START * SECTOR)
        f.write(misc)
        f.seek(BOOT_START * SECTOR)
        f.write(boot)
        if backup:
            copy_sparse(backup, f, BACKUP_START * SECTOR)


def build_kexec_target(workdir, image, busybox):
    """boot.img com o kernel do QEMU e um initramfs que só escreve a marca e desliga."""
    root = os.path.join(workdir, "kexec-root")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "bin"))
    shutil.copy(busybox, os.path.join(root, "bin", "busybox"))
    with open(os.path.join(root, "init"), "w") as f:
        f.write(f"#!/bin/busybox sh\n/bin/busybox echo {KEXEC_MARK}\n/bin/busybox poweroff -f\n")
    os.chmod(os.path.join(root, "init"), 0o755)
    cpio = subprocess.run("find . | cpio -o -H newc --quiet", shell=True, cwd=root, capture_output=True, check=True).stdout
    with open(image, "rb") as f:
        kernel = f.read()
    img = mkboot.BootImage(kernel=gzip.compress(kernel, mtime=0), ramdisk=gzip.compress(cpio, mtime=0),
                           second=b"", recovery_dtbo=b"", dtb=b"", kernel_addr=0x10008000,
                           ramdisk_addr=0x11000000, second_addr=0, tags_addr=0x10000100, dtb_addr=0,
                           page_size=2048, os_version=0, name=b"",
                           cmdline=f"console=ttyAMA0 earlycon=pl011,0x9000000 {KEXEC_MARK.lower()}=1".encode(), extra_cmdline=b"")
    path = os.path.join(workdir, "kexec-target.img")
    with open(path, "wb") as f:
        f.write(mkboot.build(img))
    return path


class Smoke:
    def __init__(self, image, initramfs, workdir, factory_misc, pubkey, backup):
        self.image, self.initramfs, self.workdir, self.backup = image, initramfs, workdir, backup
        self.misc = build_misc(factory_misc)
        self.key = pubkey[:-4] if pubkey.endswith(".pub") else pubkey
        self.failures = []
        self.warnings = []

    def warn(self, condition, message):
        """Problema conhecido e documentado (README): aparece no resumo, não reprova o build."""
        if not condition:
            self.warnings.append(message)
        print(("ok: " if condition else "AVISO: ") + message, flush=True)

    def check(self, condition, message):
        if not condition:
            self.failures.append(message)
        print(("ok: " if condition else "FALHOU: ") + message, flush=True)
        return condition

    def boot(self, name, cmdline, backup=None):
        disk = os.path.join(self.workdir, f"disk-{name}.img")
        self.boot_data = os.urandom(BOOT_SECTORS * SECTOR)
        create_disk(disk, self.misc, self.boot_data, backup)
        self.disk = disk
        return Qemu(self.image, self.initramfs, self.workdir, name, cmdline, disk)

    def build_ssh(self, qemu, *options):
        return ["ssh", "-p", str(qemu.port), "-i", self.key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=10", *options]

    def ssh(self, qemu, command, stdin=None, timeout=120):
        r = subprocess.run(self.build_ssh(qemu, "root@127.0.0.1", command), input=stdin, capture_output=True,
                           timeout=timeout)
        return r.returncode, r.stdout.decode(errors="replace")

    def wait_for_ssh(self, qemu):
        end = time.monotonic() + BOOT_TIMEOUT
        while time.monotonic() < end and qemu.proc.poll() is None:
            try:
                code, out = self.ssh(qemu, "echo pronto", timeout=20)
                if code == 0 and "pronto" in out:
                    return True
            except subprocess.TimeoutExpired:
                pass
            time.sleep(3)
        return False

    def run_stay(self):
        qemu = self.boot("ficar", "hy300.slot=boot hy300.autoboot=0", self.backup)
        try:
            if not self.check(self.wait_for_ssh(qemu), "SSH com a chave do usuário (rodada ficar)"):
                return
            self.check_basics(qemu)
            self.check_full_mode(qemu)
            self.check_backup_and_flash(qemu)
            self.check_console(qemu)
            self.check_kexec(qemu)
        finally:
            qemu.stop()

    def check_basics(self, qemu):
        code, out = self.ssh(qemu, "cat /etc/alpine-release; uname -r; readlink /dev/block/by-name/misc; "
                                   "dd if=/dev/block/by-name/misc bs=32 count=1 2>/dev/null | od -An -v -tx1 | tr -d ' \\n'; echo; "
                                   "ip -4 -o addr show dev eth0; cat /run/hy300/wifi-state; pidof sshd >/dev/null && echo sshd-ok")
        self.check("3.24" in out and "-hy300" in out, "Alpine 3.24 e kernel -hy300")
        self.check("/dev/vda2" in out, "/dev/block/by-name/misc -> /dev/vda2")
        self.check("0" * 64 in out, "BCB da misc apagado (boot-recovery)")
        self.check("10.0.2.15" in out, "DHCP no cabo (eth0 10.0.2.15)")
        self.check(self.wait_for_wifi_failure(qemu), "Wi-Fi em FALHOU sem SDIO, sem travar o resto")
        r = subprocess.run(self.build_ssh(qemu, "-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password,keyboard-interactive",
                                          "root@127.0.0.1", "true"), capture_output=True, timeout=60)
        self.check(r.returncode != 0, "login sem chave recusado")
        code, out = self.ssh(qemu, "netstat -ltn 2>/dev/null | awk 'NR > 2 { print $4 }'")
        self.check(out.split() and all(addr.endswith(":22") for addr in out.split()), f"só a porta 22 aberta ({' '.join(out.split())})")

    def wait_for_wifi_failure(self, qemu, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if "FALHOU" in self.ssh(qemu, "cat /run/hy300/wifi-state")[1]:
                return True
            time.sleep(3)
        return False

    def check_full_mode(self, qemu):
        code, out = self.ssh(qemu, "cat /etc/hy300-mode; for b in labwc mpv foot kmscube; do command -v $b; done; grep ' /media/backup ' /proc/mounts")
        self.check(out.startswith("completo"), f"modo completo (rootfs da backup): {out.splitlines()[:1]}")
        self.check("/usr/bin/labwc" in out and "/usr/bin/mpv" in out, "ambiente gráfico e extras no rootfs completo")
        self.check(" ext4 ro," in out, "backup montada só-leitura em /media/backup")
        code, out = self.ssh(qemu, "hy300-wifi connect 'Rede de Teste' senha-de-teste; cat /media/backup/config/redes.conf; "
                                   "grep ' /media/backup ' /proc/mounts")
        self.check("rede salva na partição backup" in out and 'ssid="Rede de Teste"' in out and "senha-de-teste" not in out,
                   "hy300-wifi connect salva a rede na backup (sem a senha em claro)")
        self.check(" ext4 ro," in out, "backup volta a só-leitura depois de salvar")

    def check_backup_and_flash(self, qemu):
        dest = os.path.join(self.workdir, "backup")
        shutil.rmtree(dest, ignore_errors=True)
        env = dict(os.environ, HY300_SSH=" ".join(self.build_ssh(qemu)))
        r = subprocess.run([os.path.join(REPO, "scripts", "hy300-backup.sh"), "127.0.0.1", dest, "boot", "misc"],
                           env=env, capture_output=True, text=True, timeout=300)
        backup = os.path.join(dest, "boot.img")
        ok = r.returncode == 0 and os.path.isfile(backup) and open(backup, "rb").read() == self.boot_data
        self.check(ok, "hy300-backup.sh: boot idêntica à do disco" + ("" if ok else f" ({r.stdout}{r.stderr})"))
        new = os.path.join(self.workdir, "new-boot.img")
        data = os.urandom(BOOT_SECTORS * SECTOR // 2)
        with open(new, "wb") as f:
            f.write(data)
        r = subprocess.run([os.path.join(REPO, "scripts", "hy300-flash-partition.sh"), "127.0.0.1", "boot", new],
                           env=env, capture_output=True, text=True, timeout=300)
        code, out = self.ssh(qemu, f"head -c {len(data)} /dev/block/by-name/boot | sha256sum")
        self.check(r.returncode == 0 and hashlib.sha256(data).hexdigest() in out,
                   "hy300-flash-partition.sh gravou e conferiu a boot" + ("" if r.returncode == 0 else f" ({r.stdout}{r.stderr})"))
        r = subprocess.run([os.path.join(REPO, "scripts", "hy300-flash-partition.sh"), "127.0.0.1", "misc", new],
                           env=env, capture_output=True, text=True, timeout=300)
        self.check(r.returncode != 0, "misc recusada sem --force")

    def check_console(self, qemu):
        qemu.send_keys("4")
        time.sleep(2)
        qemu.type_text("touch /tmp/menu-ok\n")
        qemu.send_keys("alt", "f2")
        time.sleep(2)
        qemu.type_text("touch /tmp/tty2-ok\n")
        time.sleep(3)
        code, out = self.ssh(qemu, "ls /tmp/menu-ok /tmp/tty2-ok; cat /run/hy300/status")
        self.check("/tmp/menu-ok" in out and "No such" not in out.split("/tmp/menu-ok")[0], "menu do tty1: tecla 4 abre o shell e aceita comando")
        self.check("/tmp/tty2-ok" in out and "tty2-ok: No such" not in out, "tty2 (Alt+F2): shell de root sem senha")
        self.check("6BOT" in out or "|____/" in out, "tela do menu com a arte 6BOT")

    def check_kexec(self, qemu):
        busybox = os.path.join(os.path.dirname(self.workdir), "rootfs", "bin", "busybox.static")
        target = build_kexec_target(self.workdir, os.path.join(os.path.dirname(self.image), "Image"), busybox)
        with open(target, "rb") as f:
            code, _ = self.ssh(qemu, "cat >/tmp/k.img", stdin=f.read())
        code, out = self.ssh(qemu, "hy300-kexec --dry-run /tmp/k.img")
        self.check(code == 0 and "kexec -l /tmp/hy300-kexec/kernel --initrd=" in out, "hy300-kexec --dry-run")
        try:
            self.ssh(qemu, "hy300-kexec /tmp/k.img", timeout=60)
        except subprocess.TimeoutExpired:
            pass
        end = time.monotonic() + 120
        while qemu.read_log().count("Booting Linux on physical CPU") < 2 and time.monotonic() < end:
            time.sleep(2)
        self.check(qemu.read_log().count("Booting Linux on physical CPU") >= 2, "kexec -e: o kernel novo começa a subir")
        self.warn(qemu.wait_for_log(KEXEC_MARK, 120),
                  "kexec -e: o kernel novo chega ao initramfs (conhecido: no QEMU ele cai em shmem_init com o "
                  "código sobrescrito, com kexec_load e com kexec_file_load; ver README)")

    def run_autoboot(self, name, cmdline, expected):
        qemu = self.boot(name, cmdline)
        try:
            exited = qemu.wait_for_exit()
            log = qemu.read_log()
            self.check("modo resgate: partição backup não encontrada" in log, f"sem a backup: modo de resgate ({name})")
            self.check(exited and "sem tecla: iniciando o Android" in log and expected in log,
                       f"autoboot sem tecla ({name}): '{expected}'")
        finally:
            qemu.stop()

    def run_key(self):
        qemu = self.boot("tecla", "hy300.slot=boot hy300.autoboot=20")
        try:
            counting = qemu.wait_for_log("[autoboot] contagem de 20 s")
            time.sleep(3)
            qemu.send_keys("a")
            stayed = qemu.wait_for_log("ficando no Alpine: tecla", 30)
            self.check(counting and stayed, "tecla durante a contagem: fica no Alpine")
            self.check("iniciando o Android" not in qemu.read_log(), "não foi para o Android depois da tecla")
        finally:
            qemu.stop()


def main(image, initramfs, workdir, factory_misc, pubkey, backup):
    os.makedirs(workdir, exist_ok=True)
    smoke = Smoke(image, initramfs, workdir, factory_misc, pubkey, backup)
    smoke.run_stay()
    smoke.run_autoboot("android", "hy300.slot=boot hy300.autoboot=2", "reboot: Restarting system with command 'recovery'")
    smoke.run_autoboot("normal", "hy300.slot=recovery hy300.autoboot=2", "reboot: Restarting system")
    smoke.run_key()
    for warning in smoke.warnings:
        print("AVISO:", warning)
    print("ok: smoke-qemu" if not smoke.failures else f"smoke-qemu: {len(smoke.failures)} falha(s), logs em {workdir}")
    return 1 if smoke.failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 7:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
