"""Autoboot da recuperação (rootfs/usr/lib/hy300/autoboot.sh e o script autoboot).

Ao subir, o Alpine conta alguns segundos na tela e vai para o Android; uma tecla (controle IR,
teclas do painel, teclado USB) faz ficar. O Android está na partição que o Alpine não ocupa:
com hy300.slot=boot ele está na recovery (reboot pelo registrador, nunca pelo BCB); com
hy300.slot=recovery ele está na boot (reboot normal).

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import time

from shelltest import LIB_DIR, ShellMixin, make_suite

AUTOBOOT = os.path.join(LIB_DIR, "autoboot")


class AutobootMixin(ShellMixin):
    libs = ("common.sh", "autoboot.sh")

    def setUp(self):
        super().setUp()
        self.fake("reboot")
        self.fake("hy300-reboot-recovery")
        self.fake("sync")
        self.fake("stay")
        self.fake("mount", 'mount\\ *sda1*) for last; do :; done; touch "$last/hy300-ficar" ;;')
        self.fake("umount")

    def env(self, cmdline="hy300.slot=boot", **extra):
        self.write("cmdline", cmdline + "\n")
        env = {"HY300_CMDLINE": self.path("cmdline"), "HY300_SYSFS_BLOCK": self.path("sys"),
               "HY300_STAY_CMD": os.path.join(self.bin, "stay"),
               "HY300_STAY_MARK_FILE": self.path("sem-marca"), "HY300_BY_NAME": self.path("sem-misc"),
               "HY300_WATCHDOG_DEV": self.path("sem-watchdog"), "HY300_WAITKEY": os.path.join(self.bin, "hy300-waitkey"),
               "HY300_PSTORE": self.path("pstore")}
        env.update(extra)
        return env

    def waitkey(self, result):
        word = "tecla 30 1200 2.4G Composite Devic" if result == "tecla" else result
        lines = "echo 2; echo 1; " + f"echo {word}"
        self.fake("hy300-waitkey", f'hy300-waitkey*) {lines}; [ {result} = tecla ] ;;')

    def test_android_slot_is_the_other_partition(self):
        r = self.sh("read_android_slot", env=self.env("hy300.slot=boot"))
        self.assertEqual(r.stdout.strip(), "recovery")
        r = self.sh("read_android_slot", env=self.env("hy300.slot=recovery"))
        self.assertEqual(r.stdout.strip(), "boot")
        r = self.sh("read_android_slot", env=self.env("console=tty0"))
        self.assertEqual(r.stdout.strip(), "desconhecido")

    def test_delay_comes_from_cmdline(self):
        self.assertEqual(self.sh("read_autoboot_delay", env=self.env("hy300.autoboot=12")).stdout.strip(), "12")
        self.assertEqual(self.sh("read_autoboot_delay", env=self.env("x=1")).stdout.strip(), "5")
        self.assertEqual(self.sh("read_autoboot_delay", env=self.env("hy300.autoboot=x")).stdout.strip(), "5")

    def test_stay_reasons(self):
        r = self.sh('read_stay_reason 0 recovery', env=self.env())
        self.assertIn("hy300.autoboot=0", r.stdout)
        r = self.sh('read_stay_reason 5 desconhecido', env=self.env())
        self.assertIn("partição do Android desconhecida", r.stdout)
        r = self.sh('read_stay_reason 5 recovery', env=self.env())
        self.assertEqual(r.stdout.strip(), "")

    def test_ready_clears_boot_failure_counter(self):
        misc = bytearray(4 * 1024 * 1024)
        misc[0x10010:0x10020] = b"hy300-boots\0\x02\0\0\0"
        self.write("by-name/misc", bytes(misc))
        self.waitkey("tecla")
        env = self.env("hy300.slot=boot")
        env["HY300_BY_NAME"] = self.path("by-name")
        self.sh(f'sh "{AUTOBOOT}"', env=env)
        with open(self.path("by-name/misc"), "rb") as f:
            f.seek(0x10010)
            self.assertEqual(f.read(16), bytes(16))
        self.assertIn("pronto", self.kmsg())

    def test_misc_mark_from_stage1_stays_without_countdown(self):
        self.write("etc-hy300-stay", "marca na misc\n")
        self.waitkey("tempo")
        env = self.env("hy300.slot=boot hy300.autoboot=5")
        env["HY300_STAY_MARK_FILE"] = self.path("etc-hy300-stay")
        self.sh(f'sh "{AUTOBOOT}"', env=env)
        log = self.fake_log()
        self.assertIn("stay marca na misc", log)
        self.assertFalse(any(line.startswith("hy300-waitkey") for line in log))
        self.assertIn("ficando no Alpine: marca na misc", self.kmsg())

    def write_panic_record(self, name="dmesg-ramoops-0"):
        self.write(f"pstore/{name}", "Panic#1 Part1\n<6>[    5.0] Booting Linux\n"
                   "<0>[   65.802592] Kernel panic - not syncing: watchdog pretimeout event\n")
        self.write("pstore/console-ramoops-0", "[    4.8] Linux version 6.1.172-hy300\n")

    def test_panic_in_pstore_stays_without_countdown(self):
        self.write_panic_record()
        self.waitkey("tempo")
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot hy300.autoboot=5"))
        log = self.fake_log()
        reason = "panic no boot anterior: watchdog pretimeout event"
        self.assertIn(f"stay {reason}", log)
        self.assertFalse(any(line.startswith(("hy300-waitkey", "hy300-reboot-recovery")) for line in log))
        self.assertIn(f"ficando no Alpine: {reason}", self.kmsg())

    def test_panic_record_is_saved_in_run_and_removed_from_pstore(self):
        self.write_panic_record()
        self.waitkey("tempo")
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot"))
        self.assertFalse(os.path.exists(self.path("pstore/dmesg-ramoops-0")), "o próximo boot não pode ficar de novo")
        saved = self.path("run/pstore-anterior")
        self.assertIn("Kernel panic", open(os.path.join(saved, "dmesg-ramoops-0")).read())
        self.assertIn("Linux version", open(os.path.join(saved, "console-ramoops-0")).read())

    def test_panic_record_is_consumed_even_with_the_misc_mark(self):
        self.write_panic_record()
        self.write("etc-hy300-stay", "marca na misc\n")
        self.waitkey("tempo")
        env = self.env("hy300.slot=boot")
        env["HY300_STAY_MARK_FILE"] = self.path("etc-hy300-stay")
        self.sh(f'sh "{AUTOBOOT}"', env=env)
        self.assertFalse(os.path.exists(self.path("pstore/dmesg-ramoops-0")))
        self.assertTrue(any(line.startswith("stay ") for line in self.fake_log()))

    def test_oops_without_panic_still_boots_android(self):
        self.write("pstore/dmesg-ramoops-0", "Oops#1 Part1\n<4>[ 30.0] WARNING: something\n")
        self.waitkey("tempo")
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot hy300.autoboot=2"))
        self.assertIn("hy300-reboot-recovery ", self.fake_log())

    def test_late_stay_reason_from_run_file(self):
        self.write("run/ficar", "")
        r = self.sh("read_late_stay_reason", env=self.env())
        self.assertIn("ficar", r.stdout)

    def test_late_stay_reason_from_usb_flag(self):
        self.write("sys/sda/uevent", "DEVTYPE=disk\n")
        self.write("sys/sda1/uevent", "DEVTYPE=partition\n")
        r = self.sh("read_late_stay_reason", env=self.env())
        self.assertIn("pendrive", r.stdout)
        self.assertIn("umount", " ".join(self.fake_log()))

    def test_countdown_text(self):
        r = self.sh("build_countdown_text 5", env=self.env())
        self.assertIn("iniciando o Android em 5 s", r.stdout)
        self.assertIn("Aperte qualquer tecla do teclado", r.stdout)
        self.assertNotIn("—", r.stdout)

    def test_no_key_boots_android_in_recovery_by_register(self):
        self.waitkey("tempo")
        r = self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot hy300.autoboot=2"))
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.fake_log()
        self.assertIn("hy300-reboot-recovery ", log)
        self.assertNotIn("reboot ", log)
        self.assertNotIn("stay", " ".join(log))
        screen = open(self.path("tty1")).read()
        self.assertIn("Iniciando o Android", screen)
        self.assertTrue(os.path.exists(self.path("run/watchdog-off")), "watchdog preparado antes do Android")

    def test_no_key_boots_android_in_boot_with_normal_reboot(self):
        self.waitkey("tempo")
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=recovery hy300.autoboot=2"))
        log = self.fake_log()
        self.assertIn("reboot ", log)
        self.assertNotIn("hy300-reboot-recovery ", log)

    def test_key_press_stays_and_logs_which_key_and_device(self):
        self.waitkey("tecla")
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot"))
        log = self.fake_log()
        reason = "tecla 30 aos 1200 ms em 2.4G Composite Devic"
        self.assertIn(f"stay {reason}", log)
        self.assertIn(f"ficando no Alpine: {reason}", self.kmsg())
        self.assertFalse(any(line.startswith(("reboot", "hy300-reboot-recovery")) for line in log))

    def test_autoboot_zero_stays_without_countdown(self):
        self.waitkey("tempo")
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot hy300.autoboot=0"))
        log = self.fake_log()
        self.assertFalse(any(line.startswith("hy300-waitkey") for line in log))
        self.assertTrue(any(line.startswith("stay ") for line in log), log)

    def test_run_file_during_countdown_stays(self):
        self.fake("hy300-waitkey", 'hy300-waitkey*) touch "$HY300_RUN/ficar"; echo tempo; exit 1 ;;')
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot"))
        self.assertTrue(any(line.startswith("stay ") for line in self.fake_log()))

    def test_failed_reboot_falls_back_to_staying(self):
        self.waitkey("tempo")
        self.fake("hy300-reboot-recovery", 'hy300-reboot-recovery*) exit 1 ;;')
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot"))
        self.assertIn("stay falha ao reiniciar para o Android", self.fake_log())

    def test_stuck_waitkey_is_cut_by_the_deadline(self):
        self.fake("hy300-waitkey", 'hy300-waitkey*) echo 1; exec sleep 30 ;;')
        start = time.monotonic()
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot hy300.autoboot=1"))
        self.assertLess(time.monotonic() - start, 10)
        self.assertIn("hy300-reboot-recovery ", self.fake_log())

    def test_broken_waitkey_still_boots_android(self):
        self.fake("hy300-waitkey", 'hy300-waitkey*) exit 127 ;;')
        self.sh(f'sh "{AUTOBOOT}"', env=self.env("hy300.slot=boot"))
        self.assertIn("hy300-reboot-recovery ", self.fake_log())


make_suite(globals(), AutobootMixin)
