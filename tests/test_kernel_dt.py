"""DT do kernel do Alpine (branch hy300-6.1): teclas do gpio-keys contra o DT de fábrica.

A tecla de energia no GPIO1_B0 (o LED "green", saída em nível baixo) com IRQ_TYPE_NONE disparava
sem parar na CPU0 (~270 mil interrupções por segundo). A conferência é o tools/dt_gpio_irq.py
do hy300-rk3566, a mesma que o build.sh roda depois de compilar o DTB.

Rodar: python3 -I -m unittest discover -s tests
Usa o DTB de KBUILD_OUT (padrão ~/hy300-work/kbuild-recovery); pulado sem ele ou sem o hy300-rk3566.
"""
import os
import sys
import unittest

HY300_RK3566 = os.environ.get("HY300_RK3566", os.path.expanduser("~/hy300-handoff/hy300-rk3566"))
KOUT = os.environ.get("KBUILD_OUT", os.path.expanduser("~/hy300-work/kbuild-recovery"))
DTB = os.path.join(KOUT, "arch", "arm64", "boot", "dts", "rockchip", "rk3566-hy300.dtb")
FACTORY_DTB = os.path.join(HY300_RK3566, "device-tree", "rk3566-hy300-txcz.dtb")
TOOL = os.path.join(HY300_RK3566, "tools", "dt_gpio_irq.py")

sys.path.insert(0, os.path.join(HY300_RK3566, "tools"))


@unittest.skipUnless(os.path.exists(TOOL) and os.path.exists(DTB), "sem o hy300-rk3566 ou sem o DTB compilado")
class KernelDtTest(unittest.TestCase):
    def test_gpio_keys_have_no_problems_against_factory(self):
        import dt_gpio_irq

        self.assertEqual(dt_gpio_irq.problems(dt_gpio_irq.load(DTB), dt_gpio_irq.load(FACTORY_DTB)), [])

    def test_power_key_is_gpio1_a0(self):
        import dt_gpio_irq

        keys = dt_gpio_irq.keys(dt_gpio_irq.load(DTB))
        self.assertEqual([(k.code, k.pin) for k in keys], [(116, 0)])


if __name__ == "__main__":
    unittest.main()
