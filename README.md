# hy300-alpine

Alpine Linux (aarch64) como ambiente de recuperação e instalação do projetor HY300 (Rockchip
RK3566, 1,5 GB de RAM), com o kernel 6.1 do HY300
([kernel-hy300-rk3566](https://github.com/mateusseiboth/kernel-hy300-rk3566), branch `hy300-6.1`).
Ao ligar, conta 5 segundos na projeção e inicia o Android, a menos que alguém aperte uma tecla
no teclado USB. Ficando, conecta no Wi-Fi (ou abre um ponto de acesso próprio), abre SSH e mostra
um menu. Dali se faz backup e gravação de partições (inclusive a `super`), kexec de kernels de
teste, testes de hardware e, opcionalmente, um ambiente gráfico.

Projeto principal e documentação do aparelho: [hy300-rk3566](https://github.com/mateusseiboth/hy300-rk3566)
(`docs/HANDOFF.md`, `docs/kernel-6.1.md`).

## Onde fica

| Partição | Tamanho | O que vai | Imagem (`~/hy300-work/alpine/`) |
|---|---|---|---|
| `boot` | 40 MiB | kernel (`Image.gz`) + initramfs: estágio 1 e o **núcleo** (modo de resgate) | `boot-alpine.img` |
| `recovery` | 108 MiB | o Android (o de fábrica agora, o LineageOS depois) | (a do Android) |
| `backup` | 372 MiB | ext4 `hy300-alpine`: o **Alpine completo** (`rootfs.sqfs`) e `config/` | `backup-alpine.img` |

A `backup` vem zerada de fábrica (o `backup.img` em `~/hy300-backup` é todo zero) e nada no
Android a usa. O Alpine entra no Android pelo registrador do reboot-mode
(`reboot(RESTART2, "recovery")`, o `kernel/reboot-recovery` do hy300-rk3566), nunca pelo BCB.

Teste em fases: antes de tocar na `boot`, o mesmo kernel e initramfs vão no slot de teste
(`recovery`), com o Android de fábrica ainda na `boot`:

| Imagem | Partição | Android em | Ir para o Android |
|---|---|---|---|
| `recovery-alpine.img` | recovery (113.246.208 bytes) | boot | reboot normal |
| `boot-alpine.img` | boot (41.943.040 bytes) | recovery | `reboot(RESTART2, "recovery")` |
| `recovery-alpine-image-crua.img` | recovery | boot | reboot normal (kernel sem compressão) |

As três têm o mesmo initramfs e a mesma seção dtb; mudam o resource (o de cada partição de
fábrica; a `boot` leva o da `boot` atual, com a capivara), o padding, o kernel da terceira e
`hy300.slot=` na cmdline, que diz ao Alpine onde ele está e onde está o Android. A terceira serve
para separar um problema da `Image.gz` (não provada no U-Boot de fábrica) de um problema do Alpine.
Cada imagem tem o `.sha256` ao lado.

### Modo completo e modo de resgate

O estágio 1 (`initramfs/init`) acha a `backup` pelo nome (`PARTNAME` no sysfs), monta o ext4 dela
só-leitura, confere o `rootfs.sqfs` pelo `rootfs.sqfs.sha256` (uns segundos; `hy300.verify=0`
pula) e usa esse rootfs: é o **modo completo**. Se a partição faltar, não for ext4, não tiver o
Alpine ou o hash não conferir, ele usa o squashfs embutido no initramfs: o **modo de resgate**,
com a tela dizendo `MODO DE RESGATE: <motivo>`. O resgate é o núcleo: Wi-Fi da rede de casa e
ponto de acesso, SSH, menu e console pelo teclado, autoboot para o Android, `dd`, `zstd`,
`sgdisk`, e2fsprogs, `lp*`, `kexec`. Basta para regravar a `backup` pela rede:

```bash
scripts/hy300-flash-partition.sh <IP> backup ~/hy300-work/alpine/backup-alpine.img
```

Nos dois modos o rootfs fica comprimido na RAM com um tmpfs gravável por cima (overlayfs), e a
`backup` segue montada só-leitura em `/media/backup`.

## Estado (22/11/2026)

| Item | Estado |
|---|---|
| Build, testes no host (184), teste de fumaça no QEMU | passando (ver "Testes") |
| Imagens no aparelho | **não testadas** |
| `Image.gz` pelo U-Boot de fábrica | não testada (as strings sugerem gzip/lz4); a `Image` crua é a provada |
| Wi-Fi (AIC8800D80) com IP fixo, SDIO a 50 MHz | driver e firmware que funcionaram no initramfs de teste do 6.1; no Alpine, não testado |
| Ponto de acesso próprio (hostapd no AIC8800) | não testado: o driver declara o modo AP, ninguém usou |
| Panfrost e ambiente gráfico | módulo compilado, DT ajustado, pacotes no rootfs completo; não testados (o QEMU não tem a GPU) |
| kexec | no QEMU o `kexec -e` entrega ao kernel novo, que cai cedo (ver "kexec"); no aparelho, não testado |

## Na tela

Ao ligar, depois do logo e do log do kernel:

```
  Alpine: iniciando o Android em 5 s.

  Aperte qualquer tecla do teclado para ficar no Alpine.
```

Sem tecla, `Iniciando o Android...` e o reboot. Qualquer tecla de qualquer dispositivo de entrada
vale (o `hy300-waitkey` lê todos os `/dev/input/event*`). Também ficam no Alpine, sem contagem
ou no fim dela: `hy300.autoboot=0` na cmdline (build com `AUTOBOOT=0`; `AUTOBOOT=N` muda os
segundos), um pendrive com um arquivo `hy300-ficar` na raiz, `/run/hy300/ficar` criado durante a
contagem, ou uma imagem sem `hy300.slot`.

Ficando, o menu no tty1 (fonte Terminus 16x32, 64x18 caracteres):

```
     __    ____     ___    _____
    / /_  | __ )   / _ \  |_   _|
   | '_ \ |  _ \  | | | |   | |
   | (_) || |_) | | |_| |   | |
    \___/ |____/   \___/    |_|

  Alpine 3.24.4 na partição boot. Android na recovery.
  Wi-Fi wlan0: 192.168.x.y (conectado em Casa)
  No PC: ssh root@192.168.x.y
  No ar há 2 min. SoC a 61 °C. RAM livre: 1210 MB.

  1 Atualizar  2 Iniciar o Android  3 Escolher rede  4 Shell
  5 Ambiente gráfico
```

Tudo pelo teclado USB (o receptor 2.4G do teclado com touchpad), uma tecla numérica por vez:
`2` reinicia para o Android, `3` procura redes Wi-Fi, pede o número e a senha (Enter vazio para
rede aberta), `4` abre um shell de root ali mesmo (`exit` volta), `5` abre o ambiente gráfico
(só no modo completo). `Alt+F2` leva a outro shell de root (tty2), sem senha, sem depender de
rede; `Alt+F1` volta ao menu. O controle IR não é usado no Alpine.

## Como entrar pelo SSH

```bash
ssh -o UserKnownHostsFile=~/hy300-work/alpine/known_hosts root@<IP>
```

Só root, só pela chave do PC (`~/.ssh/id_rsa.pub` no momento do build); senha e telnet não
existem. A chave do servidor (ed25519) é gerada no primeiro build e guardada em
`~/hy300-work/alpine/ssh-host/`, então o fingerprint não muda entre builds; o `known_hosts` traz o
IP fixo de casa e o do ponto de acesso. No aparelho, `hy300-help` lista tudo.

## Wi-Fi

O daemon (`/usr/lib/hy300/wifi`) tem três modos:

1. **station**: `wpa_supplicant` com as redes conhecidas. A rede de casa (do
   `~/hy300-work/wifi/credenciais.conf`, marcada com `id_str="casa"`) recebe o IP fixo de lá;
   qualquer outra usa DHCP. Sem conexão em 45 s, vai para o ponto de acesso.
2. **connected**: acompanha a conexão; sem sinal por 3 min, volta a procurar.
3. **ap**: ponto de acesso próprio, rede **`HY300-6bot-recovery`**, WPA2, senha de 12 caracteres
   gerada no primeiro build (`~/hy300-work/alpine/ap.conf`, modo 600) e mostrada na tela; o
   aparelho fica em `192.168.50.1` e dá IP por DHCP (`udhcpd`) de `.10` a `.50`. Sem internet:
   conecte o celular ou o PC e `ssh root@192.168.50.1`.

O driver sobe com `sdio_clock=50000000`: o SDIO a 50 MHz, como no Android de fábrica (commit
`0408d7166c75` do `hy300-6.1`).

Pelo SSH: `hy300-wifi status`, `hy300-wifi scan`, `hy300-wifi connect "Nome" senha`,
`hy300-wifi reconnect`, `hy300-wifi ap`. Pelo teclado: opção `3` do menu. Redes acrescentadas
usam DHCP, têm prioridade sobre a de casa e ficam salvas: o bloco `network={...}` (PSK já
derivada, sem a senha em claro) vai para `config/redes.conf` na `backup`, que é remontada
gravável só pelo tempo de gravar e volta a só-leitura. Em todo boot as redes salvas são somadas
à de casa. No modo de resgate a rede fica só na RAM.

Um adaptador USB-Ethernet (ASIX, AX88179, RTL8152/8153, CDC) recebe DHCP sozinho, a qualquer
momento.

## Comandos no aparelho

| Comando | O que faz |
|---|---|
| `hy300-status` | o texto da tela |
| `hy300-android` | reinicia para o Android (pela partição em que ele estiver) |
| `reboot` | reboot normal: sobe o que estiver na `boot` |
| `hy300-partitions` | partições por nome, dispositivo e tamanho; também em `/dev/block/by-name/` |
| `hy300-flash [--force] PART ARQ` | grava e confere o SHA-256 lendo de volta; recusa partição montada; `uboot`, `trust`, `misc` e `security` só com `--force` |
| `hy300-update-rootfs ARQ SHA256` | troca o `rootfs.sqfs` da `backup` com o Alpine rodando (vale no próximo boot) |
| `hy300-kexec [opções] boot.img` | boota o kernel de um boot.img v0 a v2 (abaixo) |
| `hy300-wifi ...` | Wi-Fi (acima) |
| `hy300-desktop` | ambiente gráfico (o mesmo da opção 5) |
| `hy300-gpu-test` | Panfrost + kmscube, sem o ambiente gráfico |
| `hy300-hwinfo` | retrato do hardware |
| `hy300-extras [pacote...]` | `apk add` pela rede, na RAM (útil no modo de resgate) |
| `logread` | log do sistema (sshd, wpa_supplicant, hostapd, DHCP) |

### Backup e gravação pelo PC

```bash
scripts/hy300-backup.sh <IP> ~/hy300-backup/alpine-$(date +%F) boot recovery misc
scripts/hy300-backup.sh <IP> <destino> --all          # tudo menos userdata
scripts/hy300-flash-partition.sh <IP> recovery minha-recovery.img
```

O backup comprime com zstd no caminho e confere o SHA-256 dos dois lados (`SHA256SUMS` no
destino). A gravação manda comprimido e o `hy300-flash` confere lendo a partição de volta.
`HY300_SSH` troca o comando ssh (porta, chave, `known_hosts`).

### A super (partições dinâmicas)

```sh
lpdump /dev/block/by-name/super                      # tabela de partições lógicas
lpunpack /dev/block/by-name/super /tmp/super/          # extrai system, vendor... (RAM ou pendrive)
```

Backup inteiro: `scripts/hy300-backup.sh <IP> <destino> super` (3 GiB, comprime bem). Uma super
nova (a do LineageOS, montada no PC com `lpmake`) precisa ser crua (`simg2img` antes), depois
`scripts/hy300-flash-partition.sh <IP> super super.raw`. O Alpine não depende da super: é ela que
será regravada ao instalar o LineageOS.

### kexec

```sh
hy300-kexec --dry-run /tmp/boot.img        # mostra o comando
hy300-kexec /tmp/boot.img                  # carrega e executa
hy300-kexec --append "loglevel=8" --inherit-androidboot /tmp/boot.img
```

Lê o header v0 a v2 do boot.img (kernel, ramdisk, dtb e cmdline), chama
`kexec -l kernel --initrd=ramdisk --dtb=dtb --command-line=...` e `kexec -e`. `--no-dtb` passa
o DT em uso; `--file` usa `kexec_file_load`; `--load-only` só carrega. A `Image.gz` é aceita.
Antes do `kexec -e`: os drivers das placas de rede saem (`unbind`), porque elas seguem fazendo
DMA na RAM e estragam o kernel novo (o teste no QEMU pegou isso com o virtio-net); o watchdog
recebe o maior prazo (~89 s) e o daemon sai com o fechamento mágico, então o kernel novo precisa
assumir o `/dev/watchdog` nesse tempo (o do HY300 arma de novo no começo do boot) ou ter
`CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED`, senão o aparelho desliga. Pelo SSH a parte final roda
destacada da sessão (a rede cai).

**Problema conhecido no QEMU:** o kernel novo começa a subir (`Booting Linux`) e cai cedo, em
`shmem_init`, com o próprio código sobrescrito por `0xa2`; igual com `kexec_load`, com
`kexec_file_load`, com a Image crua ou `Image.gz` e com a rede desligada. A causa não foi achada
(memória ainda escrita por algum dispositivo do kernel antigo, ou algo do kernel do BSP). O teste
de fumaça registra isso como aviso. No aparelho, testar com o usuário presente: se o kernel novo
travar, o watchdog desliga o aparelho em até ~89 s (volta pelo botão de energia).

## Ambiente gráfico (opcional, modo completo)

`hy300-desktop` ou a opção 5 do menu: **labwc** (compositor Wayland com janelas como no Openbox,
para mouse e teclado; o teclado sem fio tem touchpad) sobre DRM com o Panfrost, com o painel
**waybar** (Programas, Terminal, Arquivos, relógio, rede, temperatura, RAM, CPU), papel de parede
`swaybg` e menu no botão direito da área de trabalho (Terminal, Programas, Arquivos, Editor,
Navegador, Volume, Monitor, Sair). Atalhos: `Super+Enter` terminal, `Super+D` programas,
`Super+Shift+E` sai. Ao sair, volta ao menu de texto. Sem o Panfrost, o wlroots desenha por
software (`WLR_RENDERER=pixman`). O boot continua em modo texto; o núcleo da `boot` não depende
de nada disso.

Programas: foot (terminal), fuzzel (lançador), pcmanfm (arquivos), mousepad (editor), mpv
(vídeo e decodificação), imv (imagens), netsurf (navegador leve; o Firefox caberia, mas é pesado
para 1,5 GB de RAM), alsamixer, htop. Config em `rootfs/etc/xdg/labwc` e `rootfs/etc/xdg/waybar`.

### Pacotes e tamanhos (build de 22/11)

| Grupo | Lista | Pacotes | Instalado | Comprimido (xz) |
|---|---|---|---|---|
| Núcleo (boot e backup) | `config/packages.txt` | 137 | 87 MiB | 14,2 MB (`rootfs-core.sqfs`) |
| Mesa/Panfrost (GPU, LLVM), kmscube | `config/extras.txt` | 14 | 216 MiB | 51,4 MB |
| Vídeo, áudio e imagem (mpv, imv, ffmpeg, codecs) | `config/desktop.txt` | 77 | 86 MiB | 28,4 MB |
| Ambiente gráfico (labwc, waybar, GTK, fontes, netsurf) | `config/desktop.txt` | 102 | 106 MiB | 23,6 MB |
| Diagnóstico (alsa-utils, evtest, i2c-tools, htop, tmux, strace...) | `config/extras.txt` | 18 | 10 MiB | 2,6 MB |
| Bibliotecas comuns aos grupos acima | | 90 | 49 MiB | 11,6 MB |
| **Alpine completo** (`rootfs.sqfs` na backup) | | | ~560 MiB | **141 MB de 372 MiB** |

(Grupos estimados por pacote, comprimindo os arquivos de cada um; o total é o squashfs real.)
Sobram ~230 MB na `backup` para o que mais fizer sentido e para `config/`.

## Lado do Android: o BCB

Com o Alpine na `boot` e o Android na `recovery`, um `adb reboot recovery` ou "redefinir para a
fábrica" no Android grava `boot-recovery` no BCB da `misc`. O U-Boot dá prioridade ao BCB, isso
sobrevive a tirar da tomada, e o Alpine (na `boot`) nunca mais roda para apagar: o aparelho ficaria
sempre no Android. O Alpine apaga esse comando quando roda (só com `boot-recovery`, só os 2048
bytes do `bootloader_message`), mas aqui ele não chega a rodar.

Mitigação proposta (não instalada): `android/clear-bcb/`, um serviço no overlay do `/system` que
apaga o comando no `post-fs-data` e de novo no `boot_completed`:

```bash
adb root && adb remount
adb push android/clear-bcb/hy300-clear-bcb.sh /system/bin/ && adb shell chmod 755 /system/bin/hy300-clear-bcb.sh
adb push android/clear-bcb/hy300-clear-bcb.rc /system/etc/init/
adb reboot
```

O script é testado no host com uma `misc` de arquivo (`tests/test_android_clear_bcb.py`). Com ele,
o "redefinir para a fábrica" deixa de fazer efeito (não há programa de recovery para executá-lo).
No LineageOS, o mesmo `.rc` entra na árvore do aparelho.

## Como montar

Pacotes no Fedora: os do `docs/kernel-6.1.md` do hy300-rk3566 (`gcc-aarch64-linux-gnu`, `make`,
`flex`, `bison`, `bc`, `openssl-devel`, `elfutils-libelf-devel`), mais `squashfs-tools`, `xz`,
`e2fsprogs`, `gnupg2`, `zstd`, `qemu-user-static` (binfmt do aarch64, para os scripts dos
pacotes), `qemu-system-aarch64-core` (teste de fumaça) e `util-linux` (unshare, sfdisk).

```bash
git -C ~/hy300-handoff/kernel-hy300-rk3566 worktree add ~/hy300-work/kernel-recovery-wt hy300-6.1
./build.sh               # tudo, inclusive o teste no QEMU
SMOKE=0 ./build.sh       # sem o QEMU
```

O que o `build.sh` lê do PC (nada disso vai para o repositório):

| Entrada | Padrão |
|---|---|
| chave pública para o `authorized_keys` | `~/.ssh/id_rsa.pub` (`SSH_PUBKEY`); falha se faltar |
| rede de casa e IP fixo | `~/hy300-work/wifi/credenciais.conf` (modo 600; formato no `docs/kernel-6.1.md`) |
| firmware do AIC8800D80 | `~/hy300-work/vendor.img`, conferido por MD5 (`tools/wifi_payload.py` do hy300-rk3566) |
| recovery de fábrica | `~/hy300-backup/recovery.img`, conferida pelo `SHA256SUMS` |
| boot atual (com a splash) | `~/hy300-backup/estado-20261122/particoes/boot.img`, conferida pelo `SHA256SUMS` dali |

Passos: kernel (`Image`, módulos, dtb; confere `config/kernel-required.txt`) e `Image.gz`;
`hy300-waitkey` e o `reboot-recovery` do hy300-rk3566, estáticos com musl; Alpine 3.24.4
(`tools/alpine_fetch.py`: GPG do minirootfs com a impressão digital do Natanael Copa fixada,
chaves x86_64 do alpine-keys de dentro dele, APKINDEX e apk-tools-static conferidos por RSA e
datahash); dois rootfs num user namespace (`unshare --map-auto --map-root-user`, sem root) com o
`apk.static --arch aarch64`, cujos scripts de pacote rodam pelo binfmt do qemu-aarch64:
núcleo (`packages.txt`) e completo (`packages.txt`, `extras.txt`, `desktop.txt`);
`config/prune.txt` apaga python3 e protoc, puxados à toa pelos `android-tools-*`; squashfs xz de
cada um; `backup-alpine.img` (ext4 do tamanho exato da partição, `mke2fs -d` no user namespace);
initramfs (estágio 1, busybox estático, reboot-recovery e o núcleo) em xz; as três imagens de
boot com `tools/mkimage.py` (sobre o `mkboot.py` do hy300-rk3566; tira os parâmetros repetidos da
cmdline da recovery de fábrica para caber nos 512 bytes); conferência de cada seção;
`known_hosts`; teste no QEMU.

Rootfs e downloads ficam em `/mnt/hd/hy300-alpine/build` (`BUILD_DIR`); imagens, chave do
servidor, senha do ponto de acesso e `known_hosts` em `~/hy300-work/alpine` (`OUT`). As imagens
têm a rede de casa, a senha do ponto de acesso e a chave do servidor: não publicar.

### Tamanho da boot (build de 22/11)

| Peça | Bytes |
|---|---|
| `Image.gz` (Image crua: 41.714.176) | 14.973.076 |
| initramfs (núcleo em squashfs xz + busybox + estágio 1) | ~14.585.000 |
| resource da `boot` (logo da capivara) | 2.936.832 |
| dtb | 168.061 |
| **boot-alpine.img usado** | **~32,7 MB de 41.943.040 (sobram ~9,3 MB)** |

Plano B, se a `Image.gz` falhar no U-Boot: a `Image` crua mais o initramfs dão ~59 MB, longe dos
40 MiB. Para caber, o kernel teria de perder ~18 MB: tirar do `rockchip_linux_defconfig` o que o
HY300 não tem (DVB, câmeras e ISP, NPU, PCIe, SATA, Ethernet, Bluetooth, bcmdhd, codecs de
áudio de outras placas, MPP/RGA, Mali 400), que hoje vai embutido. Com o Alpine completo na
`backup`, o núcleo do initramfs também pode encolher. Não testado.

## Como gravar e testar (no aparelho, com o usuário presente)

Fase 1, Alpine no slot de teste, com a `backup` gravada antes (pelo Android de fábrica):

```bash
scripts/flash-backup-from-android.sh                       # backup: só se estiver zerada ou com imagem nossa
cd ~/hy300-handoff/hy300-rk3566
scripts/flash-test-recovery.sh ~/hy300-work/alpine/recovery-alpine.img
TEST_IMAGE=~/hy300-work/alpine/recovery-alpine.img scripts/reboot-to-test-slot.sh --dry-run
TEST_IMAGE=~/hy300-work/alpine/recovery-alpine.img scripts/reboot-to-test-slot.sh
```

O `flash-backup-from-android.sh` segue o `flash-test-recovery.sh`: `adb push` para
`/data/local/tmp`, confere o hash da cópia, `dd`, confere o hash gravado e registra em
`~/hy300-work/alpine/backup-gravadas.txt`. Recusa a partição se ela não estiver toda zerada nem
tiver uma imagem registrada (depois que o Alpine salva uma rede o hash muda: atualize com o
`hy300-update-rootfs` ou zere a partição antes). Para devolver a `backup` ao estado de fábrica:
`adb shell dd if=/dev/zero of=/dev/block/by-name/backup bs=4M`.

Na projeção: logo do U-Boot, log do kernel (fonte grande), a contagem. Uma tecla do teclado USB:
o menu com a arte 6BOT e, em ~30 s, o Wi-Fi conectado com o IP fixo e `ssh root@<IP>`. Sem tecla,
o Android de fábrica volta sozinho (reboot normal). Se a imagem com `Image.gz` não subir (logo
parado, sem ventoinha), tirar da tomada (volta ao Android) e repetir com
`recovery-alpine-image-crua.img`. Sem a `backup` gravada, o mesmo boot cai no modo de resgate.
De volta à recovery de fábrica: `scripts/flash-test-recovery.sh ~/hy300-backup/recovery.img`.

Fase 2, a troca de papéis (Alpine na `boot`, Android na `recovery`): só depois da fase 1 e com o
lado do Android pronto (BCB, acima).

## Riscos

1. **BCB com o Android na recovery** (acima): mitigação no lado do Android, não instalada.
2. **Laço de panic com o Alpine na boot.** Um kernel que dá panic (ou trava e o watchdog
   desliga) volta para a `boot`: o mesmo Alpine. Tirar da tomada não ajuda. Mitigação possível
   (não implementada): o kernel gravar `mode-recovery` no registrador no começo do boot e o
   Alpine gravar `normal` quando estiver de pé, sem o notificador de panic sobrescrever. Por isso
   a fase 1 vem primeiro. Uma `backup` estragada não causa isso: cai no modo de resgate.
3. **`Image.gz`** não provada no U-Boot de fábrica (imagem crua de reserva acima).
4. **initramfs** de 14,6 MB em xz (o do marco 1 tinha 0,7 MB; o da recovery de fábrica, 46,5 MB).
5. **Watchdog**: o daemon do busybox o alimenta a cada 10 s (prazo 60 s), com `oom_score_adj`
   -1000, reiniciado pelo init se morrer. O `sysinit` precisa terminar antes de ~89 s do boot
   (espera a `misc` por até 15 s); o estágio 1 confere o hash do rootfs completo antes (alguns
   segundos).
6. **Ponto de acesso** não testado no AIC8800; se não abrir, a tela mostra `FALHOU` e o daemon
   tenta a rede de novo a cada minuto.
7. **Pacotes podados**: o banco do apk ainda lista `python3` e `protoc`; `apk fix` os traz.
8. **ext4 da backup**: só fica gravável durante uma gravação de config ou de rootfs. Um corte de
   energia nesse instante fica com o journal; um `config/` estragado não impede o boot.

## Arquitetura

- **Estágio 1** (`initramfs/init`, busybox estático): `backup` ou núcleo, squashfs por loop e
  tmpfs por cima (overlayfs), `switch_root` para o `/sbin/init`. Falhando até o núcleo: mensagem
  na tela e no pstore e reboot para o Android em 60 s.
- **Init**: busybox init com `/etc/inittab` próprio, sem OpenRC. A ordem é fixa (montagens, redes
  salvas e BCB; watchdog; sshd; autoboot e menu no tty1; shell no tty2) e o OpenRC traria
  scripts de rede, udev/mdev e um boot mais lento sem ganho.
- **Scripts** em `/usr/lib/hy300/` (shell POSIX, funções com verbo em inglês, mensagens em
  português), comandos em `/usr/sbin/hy300-*`, programa em C em `src/` (`hy300-waitkey`).
- **Kernel**: fragmento `rk3566_hy300.config` do `hy300-6.1` com overlayfs, f2fs, erofs, exfat, dm,
  `KEXEC_FILE`, Ethernet USB, Panfrost (módulo) e a fonte Terminus 16x32; DT da GPU no formato do
  Panfrost; parâmetro `sdio_clock` do AIC8800. Já tinha VT, `VT_CONSOLE`, fbcon, USB HID genérico e
  evdev (teclado USB no console e no autoboot). Na imagem só vão os módulos do
  `config/modules.txt` (AIC8800, Panfrost).

## Testes

```bash
python3 -I -m unittest discover -s tests      # host: shell, Python e o hy300-waitkey (gcc)
```

No host (184 testes): partições por nome e BCB, leitura de boot.img e `hy300-kexec` (inclusive o
unbind das placas de rede), autoboot (as duas partições, tecla, pendrive, falha), menu, tela (cabe
em 64x18, sem travessão, arte 6BOT, modo de resgate), rede (casa com IP fixo, outra com DHCP,
ponto de acesso, acrescentar rede, scan), persistência na `backup`, `hy300-flash`,
`hy300-update-rootfs`, `hy300-waitkey` (eventos de teclado num arquivo), assinatura dos .apk e GPG,
entradas do build, `mkimage`, gravação da `backup` pelo Android (adb falso) e a proposta do BCB.
Os testes em shell rodam no `/bin/sh` do host e no busybox do Alpine (binfmt), se o rootfs já foi
montado.

No QEMU (`tests/smoke_qemu.py`, chamado pelo `build.sh`; `virt` com o kernel do `hy300-6.1` mais
PL011, virtio e teclado virtio, e o mesmo initramfs da imagem):

- com a `backup` no disco (a imagem real): modo completo, labwc e mpv presentes, `backup` só-
  leitura, rede salva nela sem a senha em claro e de volta a só-leitura; login por chave e senha
  recusada, só a porta 22, `/dev/block/by-name`, BCB apagado, DHCP no cabo, Wi-Fi em `FALHOU`
  sem travar, backup e gravação com os scripts do PC, `misc` recusada sem `--force`, tecla `4` do
  menu abre o shell e aceita comando, `Alt+F2` dá o shell do tty2, tela com a arte 6BOT,
  `hy300-kexec --dry-run` e o `kexec -e` até o kernel novo começar a subir (a marca no
  initramfs dele é um aviso conhecido, acima);
- sem a `backup`: modo de resgate, autoboot sem tecla para as duas partições (`reboot` normal e
  `RESTART2 "recovery"`) e tecla durante a contagem (fica).
