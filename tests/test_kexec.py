"""Leitura de boot.img Android (bootimg.sh) e o comando hy300-kexec.

O boot.img de teste sai do tools/mkboot.py do hy300-rk3566 (o mesmo que monta as imagens do
HY300). O kexec, o sync e o watchdog são falsos: o teste confere os argumentos e a ordem.

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import struct
import subprocess
import sys

from shelltest import REPO, ShellMixin, make_suite, read_bytes

HY300_RK3566 = os.environ.get("HY300_RK3566", os.path.expanduser("~/hy300-handoff/hy300-rk3566"))
sys.path.insert(0, os.path.join(HY300_RK3566, "tools"))
import mkboot  # noqa: E402

KEXEC = os.path.join(REPO, "rootfs", "usr", "sbin", "hy300-kexec")
CMDLINE = b"console=ttyFIQ0 androidboot.hardware=rk30board init=/init"


def build_bootimg(dtb=b"DTB" * 100, ramdisk=b"RAMDISK" * 1000, recovery_dtbo=b""):
    img = mkboot.BootImage(
        kernel=b"\x1f\x8b" + b"K" * 5000, ramdisk=ramdisk, second=b"RSCE" * 300,
        recovery_dtbo=recovery_dtbo, dtb=dtb, kernel_addr=0x10008000, ramdisk_addr=0x11000000,
        second_addr=0x10f00000, tags_addr=0x10000100, dtb_addr=0x11f00000, page_size=2048,
        os_version=0, name=b"", cmdline=CMDLINE, extra_cmdline=b"")
    return mkboot.build(img)


class KexecMixin(ShellMixin):
    libs = ("common.sh", "bootimg.sh")


    def setUp(self):
        super().setUp()
        self.fake("kexec")
        self.fake("sync")
        self.fake("hy300-watchdogd")
        self.fake("pidof", 'pidof\\ hy300-watchdogd) cat "$WATCHDOG_PIDFILE" 2>/dev/null ;;')
        self.write("cmdline", "console=tty0 androidboot.serialno=ABC androidboot.mode=normal hy300.slot=recovery\n")
        self.img = self.write("boot.img", build_bootimg())

    def env(self):
        return {"HY300_CMDLINE": self.path("cmdline"), "HY300_KEXEC_DIR": self.path("kx"),
                "HY300_SYSFS_NET": self.path("sys/class/net"),
                "HY300_WATCHDOG_DEV": self.path("watchdog-dev"), "HY300_SYSRQ": self.path("sysrq"),
                "WATCHDOG_PIDFILE": self.path("watchdog.pid")}

    def start_fake_daemon(self):
        """Processo no papel do daemon do watchdog, filho do init (sem virar zumbi do teste)."""
        subprocess.run(["sh", "-c", f'sleep 60 & echo $! >"{self.path("watchdog.pid")}"'], check=True)
        with open(self.path("watchdog.pid")) as f:
            return int(f.read())

    def is_alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def kexec(self, *args):
        quoted = " ".join(f"'{a}'" for a in args)
        return self.sh(f'sh "{KEXEC}" {quoted}', env=self.env())

    def test_read_bootimg_header_v2(self):
        r = self.sh(f'read_bootimg "{self.img}" && echo "$BOOTIMG_VERSION $BOOTIMG_PAGE $BOOTIMG_KERNEL_SIZE '
                    f'$BOOTIMG_RAMDISK_SIZE $BOOTIMG_DTB_SIZE"; echo "$BOOTIMG_CMDLINE"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["2 2048 5002 7000 300", CMDLINE.decode()])

    def test_extract_bootimg_sections_match(self):
        out = self.path("out")
        r = self.sh(f'read_bootimg "{self.img}" && extract_bootimg "{self.img}" "{out}"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_bytes(os.path.join(out, "kernel")), b"\x1f\x8b" + b"K" * 5000)
        self.assertEqual(read_bytes(os.path.join(out, "ramdisk")), b"RAMDISK" * 1000)
        self.assertEqual(read_bytes(os.path.join(out, "dtb")), b"DTB" * 100)

    def test_extract_skips_recovery_dtbo_before_dtb(self):
        self.img = self.write("boot.img", build_bootimg(recovery_dtbo=b"O" * 623))
        out = self.path("out")
        r = self.sh(f'read_bootimg "{self.img}" && extract_bootimg "{self.img}" "{out}"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_bytes(os.path.join(out, "dtb")), b"DTB" * 100)

    def test_rejects_header_v3_and_non_android(self):
        data = bytearray(build_bootimg())
        struct.pack_into("<I", data, 40, 3)
        v3 = self.write("v3.img", bytes(data))
        junk = self.write("junk.img", b"\0" * 4096)
        r = self.sh(f'read_bootimg "{v3}"; echo "v3=$?"; read_bootimg "{junk}"; echo "junk=$?"')
        self.assertIn("v3=1", r.stdout)
        self.assertIn("junk=1", r.stdout)
        self.assertIn("header v3", r.stdout + r.stderr)

    def test_dry_run_prints_command_and_loads_nothing(self):
        r = self.kexec("--dry-run", self.img)
        self.assertEqual(r.returncode, 0, r.stderr)
        kx = self.path("kx")
        self.assertIn(f"kexec -l {kx}/kernel --initrd={kx}/ramdisk --dtb={kx}/dtb "
                      f"--command-line={CMDLINE.decode()}", r.stdout)
        self.assertEqual(self.fake_log(), [])

    def test_append_and_inherit_androidboot(self):
        r = self.kexec("--dry-run", "--append", "hy300.test=1", "--inherit-androidboot", self.img)
        self.assertIn(f"--command-line={CMDLINE.decode()} androidboot.serialno=ABC androidboot.mode=normal "
                      "hy300.test=1", r.stdout)

    def test_cmdline_replaces_header_and_no_dtb_uses_running_dt(self):
        r = self.kexec("--dry-run", "--cmdline", "console=tty0 quiet", "--no-dtb", self.img)
        self.assertIn("--command-line=console=tty0 quiet", r.stdout)
        self.assertNotIn("--dtb", r.stdout)

    def test_file_mode_uses_kexec_file_load(self):
        r = self.kexec("--dry-run", "--file", self.img)
        self.assertIn("kexec -s -l ", r.stdout)

    def test_load_only_does_not_execute(self):
        r = self.kexec("--load-only", self.img)
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.fake_log()
        self.assertTrue(log[0].startswith("kexec -l "), log)
        self.assertNotIn("kexec -e", log)

    def test_execute_stops_watchdog_daemon_then_runs(self):
        daemon = self.start_fake_daemon()
        r = self.kexec(self.img)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.fake_log()
        self.assertTrue(log[0].startswith("kexec -l "), log)
        self.assertEqual(log[-1], "kexec -e")
        self.assertIn("sync ", log)
        self.assertFalse(self.is_alive(daemon))
        self.assertTrue(os.path.exists(self.path("run/watchdog-off")))

    def add_net_device(self, iface, device, driver):
        os.makedirs(self.path(f"sys/devices/{device}"), exist_ok=True)
        os.makedirs(self.path(f"sys/bus/drivers/{driver}"), exist_ok=True)
        self.write(f"sys/bus/drivers/{driver}/unbind", "")
        os.symlink(self.path(f"sys/bus/drivers/{driver}"), self.path(f"sys/devices/{device}/driver"))
        os.makedirs(self.path(f"sys/class/net/{iface}"), exist_ok=True)
        os.symlink(self.path(f"sys/devices/{device}"), self.path(f"sys/class/net/{iface}/device"))

    def test_execute_unbinds_network_drivers_first(self):
        """Placas de rede continuam fazendo DMA na RAM depois do kexec e estragam o kernel novo."""
        os.makedirs(self.path("sys/class/net/lo"))
        self.add_net_device("eth0", "virtio1", "virtio_net")
        self.add_net_device("wlan0", "mmc1:390b:1", "aicbsp_sdio")
        r = self.kexec(self.img)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(self.path("sys/bus/drivers/virtio_net/unbind")).read().strip(), "virtio1")
        self.assertEqual(open(self.path("sys/bus/drivers/aicbsp_sdio/unbind")).read().strip(), "mmc1:390b:1")
        self.assertEqual(self.fake_log()[-1], "kexec -e")

    def test_without_ramdisk_skips_initrd(self):
        self.img = self.write("boot.img", build_bootimg(ramdisk=b""))
        r = self.kexec("--dry-run", self.img)
        self.assertNotIn("--initrd", r.stdout)

    def test_failed_load_does_not_touch_watchdog(self):
        self.fake("kexec", 'kexec\\ -l*) exit 1 ;;')
        daemon = self.start_fake_daemon()
        r = self.kexec(self.img)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(self.is_alive(daemon))
        os.kill(daemon, 15)
        self.assertFalse(os.path.exists(self.path("run/watchdog-off")))


make_suite(globals(), KexecMixin)
