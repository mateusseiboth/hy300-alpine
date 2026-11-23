/*
 * ioctl falso do /dev/vendor_storage para os testes no host (tests/test_vendorstorage.py).
 * Imita o sdmmc_vendor_storage.c do kernel hy300-6.1: confere a tag, lê copiando até len bytes
 * do item (e devolve o tamanho em len), grava o item inteiro; item ausente na leitura = -1
 * (EPERM). Os itens ficam em arquivos FAKE_VENDOR_DIR/<id>, e cada chamada é registrada em
 * FAKE_VENDOR_DIR/log ("cmd=0x... id=... len=...").
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct fake_req {
	uint32_t tag;
	uint16_t id;
	uint16_t len;
	uint8_t data[1024];
};

#define FAKE_TAG 0x56524551
#define FAKE_READ 0x40047601UL
#define FAKE_WRITE 0x40047602UL

static void build_path(char *path, size_t size, const char *name)
{
	snprintf(path, size, "%s/%s", getenv("FAKE_VENDOR_DIR"), name);
}

static void log_call(unsigned long cmd, const struct fake_req *req)
{
	char path[512];
	FILE *log;

	build_path(path, sizeof(path), "log");
	log = fopen(path, "a");
	if (!log)
		return;
	fprintf(log, "cmd=0x%lx tag=0x%x id=%u len=%u\n", cmd, req->tag, req->id, req->len);
	fclose(log);
}

static int fake_read(struct fake_req *req)
{
	char path[512], name[16];
	FILE *item;
	size_t got;

	snprintf(name, sizeof(name), "%u", req->id);
	build_path(path, sizeof(path), name);
	item = fopen(path, "rb");
	if (!item) {
		errno = EPERM;
		return -1;
	}
	got = fread(req->data, 1, req->len, item);
	fclose(item);
	req->len = (uint16_t)got;
	return 0;
}

static int fake_write(const struct fake_req *req)
{
	char path[512], name[16];
	FILE *item;

	if (req->len >= 4096 - 8) {
		errno = EPERM;
		return -1;
	}
	snprintf(name, sizeof(name), "%u", req->id);
	build_path(path, sizeof(path), name);
	item = fopen(path, "wb");
	if (!item)
		return -1;
	fwrite(req->data, 1, req->len, item);
	fclose(item);
	return 0;
}

int vs_ioctl(int fd, unsigned long cmd, void *arg)
{
	struct fake_req *req = arg;

	(void)fd;
	log_call(cmd, req);
	if (req->tag != FAKE_TAG) {
		errno = EPERM;
		return -1;
	}
	if (cmd == FAKE_READ)
		return fake_read(req);
	if (cmd == FAKE_WRITE)
		return fake_write(req);
	errno = ENOTTY;
	return -1;
}
