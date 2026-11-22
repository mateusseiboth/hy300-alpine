#!/system/bin/sh
# Apaga o comando "boot-recovery" do BCB da misc no boot do Android (proposta; ver README).
#
# Com o Alpine na partição boot e o Android na recovery, o Android grava boot-recovery no BCB
# no "adb reboot recovery" e no "redefinir para a fábrica". O U-Boot dá prioridade ao BCB e
# subiria a recovery (o Android) em todo boot, inclusive depois de tirar da tomada: o Alpine
# ficaria inalcançável. Só os 2048 bytes do bootloader_message, e só com esse comando (em 0x800
# ficam os dados A/B da Rockchip; em 16 KiB um BCB legado que o U-Boot ignora).
MISC="${HY300_MISC:-/dev/block/by-name/misc}"
LOG="${HY300_LOG:-/dev/kmsg}"

command=$(dd if="$MISC" bs=32 count=1 2>/dev/null | tr '\000' '\n' | head -n 1)
case "$command" in
boot-recovery*) ;;
*) exit 0 ;;
esac
dd if=/dev/zero of="$MISC" bs=2048 count=1 conv=notrunc,fsync 2>/dev/null &&
	echo "hy300-clear-bcb: comando '$command' apagado da misc" >>"$LOG"
sync
