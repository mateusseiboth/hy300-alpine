/*
 * hy300-vendorstorage: lê e grava itens da vendor storage da Rockchip pelo /dev/vendor_storage.
 *
 * Uso: hy300-vendorstorage [-d DISPOSITIVO] read [--hex] ID
 *      hy300-vendorstorage [-d DISPOSITIVO] write [--hex] ID VALOR
 *   read imprime os bytes do item (com --hex, em hexadecimal); write grava VALOR (texto, ou
 *   bytes em hexadecimal com --hex) e confere lendo de volta. Saída 0 ok, 1 falha, 2 uso.
 *
 * Interface: o driver de vendor storage do eMMC (drivers/soc/rockchip/sdmmc_vendor_storage.c
 * do hy300-6.1) com a struct RK_VENDOR_REQ de include/uapi/misc/rkflash_vendor_storage.h:
 * tag 0x56524551 ("VREQ"), id, len e até 1024 bytes de dados; VENDOR_READ_IO =
 * _IOW('v', 1, u32) e VENDOR_WRITE_IO = _IOW('v', 2, u32). Na leitura o driver copia até len
 * bytes do item e devolve o tamanho em len. O 4.19 de fábrica usa o mesmo formato.
 *
 * Itens conhecidos do HY300: 50 = modo de instalação (1 byte ASCII '0'..'3'), lido pelo U-Boot
 * da TXCZ para girar o logo (ver hy300-orientacao).
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define VENDOR_REQ_TAG 0x56524551
#define VENDOR_DATA_MAX 1024
#define VENDOR_READ_IO _IOW('v', 0x01, uint32_t)
#define VENDOR_WRITE_IO _IOW('v', 0x02, uint32_t)
#define DEFAULT_DEVICE "/dev/vendor_storage"

struct vendor_req {
	uint32_t tag;
	uint16_t id;
	uint16_t len;
	uint8_t data[VENDOR_DATA_MAX];
};

_Static_assert(sizeof(struct vendor_req) == 1032, "RK_VENDOR_REQ tem 1032 bytes");

#ifdef HY300_VS_FAKE_IOCTL
int vs_ioctl(int fd, unsigned long cmd, void *arg);
#else
static int vs_ioctl(int fd, unsigned long cmd, void *arg)
{
	return ioctl(fd, cmd, arg);
}
#endif

static int print_usage(const char *name)
{
	fprintf(stderr, "uso: %s [-d DISPOSITIVO] read [--hex] ID\n"
			"     %s [-d DISPOSITIVO] write [--hex] ID VALOR\n", name, name);
	return 2;
}

static int parse_id(const char *text, uint16_t *id)
{
	char *end;
	long value;

	errno = 0;
	value = strtol(text, &end, 10);
	if (errno || end == text || *end || value < 0 || value > 0xffff)
		return 0;
	*id = (uint16_t)value;
	return 1;
}

static int parse_hex_digit(char c)
{
	if (c >= '0' && c <= '9')
		return c - '0';
	if (c >= 'a' && c <= 'f')
		return c - 'a' + 10;
	if (c >= 'A' && c <= 'F')
		return c - 'A' + 10;
	return -1;
}

/* Bytes do valor: o texto como está, ou pares hexadecimais com --hex. -1 se inválido. */
static int parse_value(const char *text, int hex, uint8_t *out)
{
	size_t len = strlen(text), i;
	int high, low;

	if (!hex) {
		if (len == 0 || len > VENDOR_DATA_MAX)
			return -1;
		memcpy(out, text, len);
		return (int)len;
	}
	if (len == 0 || len % 2 || len / 2 > VENDOR_DATA_MAX)
		return -1;
	for (i = 0; i < len / 2; i++) {
		high = parse_hex_digit(text[2 * i]);
		low = parse_hex_digit(text[2 * i + 1]);
		if (high < 0 || low < 0)
			return -1;
		out[i] = (uint8_t)(high << 4 | low);
	}
	return (int)(len / 2);
}

static int read_item(int fd, uint16_t id, struct vendor_req *req)
{
	memset(req, 0, sizeof(*req));
	req->tag = VENDOR_REQ_TAG;
	req->id = id;
	req->len = VENDOR_DATA_MAX;
	return vs_ioctl(fd, VENDOR_READ_IO, req);
}

static int write_item(int fd, uint16_t id, const uint8_t *data, int len)
{
	struct vendor_req req;

	memset(&req, 0, sizeof(req));
	req.tag = VENDOR_REQ_TAG;
	req.id = id;
	req.len = (uint16_t)len;
	memcpy(req.data, data, (size_t)len);
	return vs_ioctl(fd, VENDOR_WRITE_IO, &req);
}

static void print_item(const struct vendor_req *req, int hex)
{
	unsigned int i;

	if (!hex) {
		fwrite(req->data, 1, req->len, stdout);
		return;
	}
	for (i = 0; i < req->len; i++)
		printf("%02x", req->data[i]);
	printf("\n");
}

static int run_read(int fd, uint16_t id, int hex)
{
	struct vendor_req req;

	if (read_item(fd, id, &req) != 0) {
		fprintf(stderr, "hy300-vendorstorage: item %u não lido: %s\n", id, strerror(errno));
		return 1;
	}
	print_item(&req, hex);
	return 0;
}

static int run_write(int fd, uint16_t id, const uint8_t *data, int len)
{
	struct vendor_req back;

	if (write_item(fd, id, data, len) != 0) {
		fprintf(stderr, "hy300-vendorstorage: item %u não gravado: %s\n", id, strerror(errno));
		return 1;
	}
	if (read_item(fd, id, &back) != 0 || back.len != len || memcmp(back.data, data, (size_t)len) != 0) {
		fprintf(stderr, "hy300-vendorstorage: o item %u não confere depois de gravar\n", id);
		return 1;
	}
	return 0;
}

static int run_on_device(const char *device, uint16_t id, const uint8_t *value, int len, int hex)
{
	int fd = open(device, O_RDWR | O_CLOEXEC), result;

	if (fd < 0) {
		fprintf(stderr, "hy300-vendorstorage: %s: %s (o driver de vendor storage subiu? dmesg | grep 'vendor storage')\n",
			device, strerror(errno));
		return 1;
	}
	result = value ? run_write(fd, id, value, len) : run_read(fd, id, hex);
	close(fd);
	return result;
}

int main(int argc, char **argv)
{
	const char *device = DEFAULT_DEVICE, *command;
	uint8_t value[VENDOR_DATA_MAX];
	int arg = 1, hex = 0, len;
	uint16_t id;

	if (argc > 2 && strcmp(argv[1], "-d") == 0) {
		device = argv[2];
		arg = 3;
	}
	if (arg >= argc)
		return print_usage(argv[0]);
	command = argv[arg++];
	if (arg < argc && strcmp(argv[arg], "--hex") == 0) {
		hex = 1;
		arg++;
	}
	if (arg >= argc || !parse_id(argv[arg], &id))
		return print_usage(argv[0]);
	arg++;
	if (strcmp(command, "read") == 0 && arg == argc)
		return run_on_device(device, id, NULL, 0, hex);
	if (strcmp(command, "write") != 0 || arg != argc - 1)
		return print_usage(argv[0]);
	len = parse_value(argv[arg], hex, value);
	if (len <= 0)
		return print_usage(argv[0]);
	return run_on_device(device, id, value, len, hex);
}
