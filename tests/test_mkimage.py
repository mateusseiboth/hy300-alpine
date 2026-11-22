"""tools/mkimage.py: boot.img v2 do HY300 a partir de uma imagem de referência (recovery ou
boot de fábrica), com a cmdline da referência sem duplicatas mais a da recuperação.

A cmdline do header v2 tem 512 bytes e a da recovery de fábrica repete metade dos parâmetros
(447 bytes): sem tirar as repetições os parâmetros da recuperação não cabem.

Rodar: python3 -I -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import mkimage  # noqa: E402

mkboot = mkimage.mkboot
FACTORY_CMDLINE = ("console=ttyFIQ0 init=/init androidboot.hardware=rk30board "
                   "console=ttyFIQ0 init=/init androidboot.hardware=rk30board")


def build_like(cmdline=FACTORY_CMDLINE):
    img = mkboot.BootImage(kernel=b"K" * 4000, ramdisk=b"R" * 3000, second=b"RSCE" * 100,
                           recovery_dtbo=b"O" * 623, dtb=b"D" * 100, kernel_addr=0x10008000,
                           ramdisk_addr=0x11000000, second_addr=0x10f00000, tags_addr=0x10000100,
                           dtb_addr=0x11f00000, page_size=2048, os_version=0x18000067, name=b"",
                           cmdline=cmdline.encode(), extra_cmdline=b"")
    return mkboot.build(img, pad_to=64 * 1024)


class MkimageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hy300-mkimage-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_dedupe_keeps_first_occurrence_order(self):
        self.assertEqual(mkimage.build_cmdline(FACTORY_CMDLINE, "hy300.slot=boot console=tty0"),
                         "console=ttyFIQ0 init=/init androidboot.hardware=rk30board hy300.slot=boot console=tty0")

    def test_too_long_cmdline_fails(self):
        with self.assertRaisesRegex(ValueError, "512"):
            mkimage.build_cmdline("a" * 400, "b" * 120)

    def test_build_replaces_sections_keeps_rest_and_pads(self):
        like = build_like()
        img = mkimage.build_image(like, {"kernel": b"\x1f\x8b" + b"G" * 100, "ramdisk": b"N" * 10}, "hy300.slot=recovery")
        self.assertEqual(len(img), len(like))
        out = mkboot.unpack(img)
        self.assertEqual(out.kernel, b"\x1f\x8b" + b"G" * 100)
        self.assertEqual(out.ramdisk, b"N" * 10)
        self.assertEqual(out.second, b"RSCE" * 100)
        self.assertEqual(out.recovery_dtbo, b"O" * 623)
        self.assertTrue(out.cmdline.endswith(b"rk30board hy300.slot=recovery"))
        self.assertEqual(out.os_version, 0x18000067)

    def test_build_refuses_image_bigger_than_reference(self):
        like = build_like()
        with self.assertRaisesRegex(ValueError, "não cabe"):
            mkimage.build_image(like, {"ramdisk": b"N" * 70000}, "x=1")


if __name__ == "__main__":
    unittest.main()
