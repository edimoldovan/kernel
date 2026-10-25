# Plan the new GPT on the host: split partition 3 (LINUX) into EFI 500 MiB, boot 2 GiB, root. Writes only files here.
import struct, uuid, zlib, hashlib, sys
S = sys.argv[1]; LBA = 4096
prim = open(S + "/gpt-primary.bin", "rb").read(); back = open(S + "/gpt-backup.bin", "rb").read()
H = "<8sIIIIQQQQ16sQIII"
def parse_hdr(b):
    f = list(struct.unpack(H, b[:92])); return dict(zip("sig rev hsz crc res cur bak fu lu guid elba n esz ecrc".split(), f))
def hdr_bytes(h):
    return struct.pack(H, h["sig"], h["rev"], h["hsz"], h["crc"], h["res"], h["cur"], h["bak"], h["fu"], h["lu"], h["guid"], h["elba"], h["n"], h["esz"], h["ecrc"])
def with_crc(h):
    h = dict(h, crc=0); raw = hdr_bytes(h); h["crc"] = zlib.crc32(raw) & 0xffffffff; return h
def guid_str(b): return str(uuid.UUID(bytes_le=b)).upper()
ph = parse_hdr(prim[LBA:LBA+92]); bh = parse_hdr(back[4*LBA:4*LBA+92])
assert ph["sig"] == b"EFI PART" and bh["sig"] == b"EFI PART"
ents = prim[2*LBA:2*LBA + ph["n"]*ph["esz"]]
assert zlib.crc32(ents) & 0xffffffff == ph["ecrc"], "primary entries crc"
assert with_crc(ph)["crc"] == ph["crc"], "primary header crc"
bents = back[0:4*LBA][:ph["n"]*ph["esz"]]
assert bents == ents, "backup entries differ from primary"
assert with_crc(bh)["crc"] == bh["crc"], "backup header crc"
assert bh["elba"] == ph["bak"] - 4 and bh["cur"] == ph["bak"] and bh["bak"] == 1
def parse_ent(e):
    t, g, a, z, attr = struct.unpack("<16s16sQQQ", e[:56]); name = e[56:128].decode("utf-16le").rstrip("\0")
    return dict(type=t, guid=g, first=a, last=z, attr=attr, name=name)
E = [parse_ent(ents[i*128:(i+1)*128]) for i in range(ph["n"])]
print(f"disk: lbas 0..{ph['bak']} usable {ph['fu']}..{ph['lu']} guid {guid_str(ph['guid'])}")
for i, e in enumerate(E):
    if e["type"] != b"\0"*16:
        print(f"  slot {i} p{i+1}: {e['first']}-{e['last']} ({(e['last']-e['first']+1)*LBA/2**30:.1f} GiB) type {guid_str(e['type'])} name {e['name']!r}")
MSBASIC = uuid.UUID("EBD0A0A2-B9E5-4433-87C0-68B6B72699C7").bytes_le
p3 = E[2]; assert p3["type"] == MSBASIC and p3["name"] == "", p3
assert (p3["last"] - p3["first"] + 1) * 8 == 381181952, "p3 size differs from the kernel's view"
assert E[4]["type"] == b"\0"*16 and E[5]["type"] == b"\0"*16, "slots 5 and 6 not free"
for i, e in enumerate(E):
    if e["type"] != b"\0"*16 and i != 2:
        assert e["last"] < p3["first"] or e["first"] > p3["last"], "overlap with p3"
ALIGN = 256  # 1 MiB
def up(x): return (x + ALIGN - 1) // ALIGN * ALIGN
efi_first = p3["first"]; assert efi_first % ALIGN == 0, "p3 start not 1 MiB aligned"
efi_last = efi_first + 500*2**20//LBA - 1
boot_first = up(efi_last + 1); boot_last = boot_first + 2*2**30//LBA - 1
root_first = up(boot_last + 1); root_last = p3["last"]
assert root_last > root_first + 2**30//LBA
def ent(t, name, a, z):
    g = uuid.uuid4()
    return struct.pack("<16s16sQQQ", uuid.UUID(t).bytes_le, g.bytes_le, a, z, 0) + name.encode("utf-16le").ljust(72, b"\0"), str(g).upper()
new = bytearray(ents)
new[2*128:3*128], g_efi = ent("C12A7328-F81F-11D2-BA4B-00A0C93EC93B", "EFI", efi_first, efi_last)
new[4*128:5*128], g_boot = ent("0FC63DAF-8483-4772-8E79-3D69D8477DE4", "OMARCHY-BOOT", boot_first, boot_last)
new[5*128:6*128], g_root = ent("B921B045-1DF0-41C3-AF44-4C6F280D3FAE", "OMARCHY-ROOT", root_first, root_last)
new = bytes(new)
nph = with_crc(dict(ph, ecrc=zlib.crc32(new) & 0xffffffff))
nbh = with_crc(dict(bh, ecrc=nph["ecrc"]))
primary_img = hdr_bytes(nph).ljust(LBA, b"\0") + new.ljust(4*LBA, b"\0")      # LBA 1..5
backup_img = new.ljust(4*LBA, b"\0") + hdr_bytes(nbh).ljust(LBA, b"\0")       # LBA bak-4..bak
assert len(primary_img) == 5*LBA and len(backup_img) == 5*LBA
# unchanged bytes outside the three slots and the two headers
assert primary_img[LBA:][:2*128] == ents[:2*128] and primary_img[LBA:][3*128:4*128] == ents[3*128:4*128] and primary_img[LBA:][6*128:] == ents[6*128:].ljust(4*LBA-6*128, b"\0")
open(S + "/gpt-new-primary.bin", "wb").write(primary_img); open(S + "/gpt-new-backup.bin", "wb").write(backup_img)
cur_primary = prim[LBA:6*LBA]; cur_backup = back
md5 = lambda b: hashlib.md5(b).hexdigest()
print(f"EFI   p3 {efi_first}-{efi_last} ({(efi_last-efi_first+1)*LBA/2**20:.0f} MiB) {g_efi}")
print(f"BOOT  p5 {boot_first}-{boot_last} ({(boot_last-boot_first+1)*LBA/2**30:.1f} GiB) {g_boot}")
print(f"ROOT  p6 {root_first}-{root_last} ({(root_last-root_first+1)*LBA/2**30:.1f} GiB) {g_root}")
print("backup region lba", ph["bak"]-4, "..", ph["bak"])
print("md5 current primary(1..5)", md5(cur_primary)); print("md5 current backup", md5(cur_backup))
print("md5 new primary", md5(primary_img)); print("md5 new backup", md5(backup_img))
open(S + "/gpt-facts.txt", "w").write(f"BAK={ph['bak']}\nCUR_PRIMARY_MD5={md5(cur_primary)}\nCUR_BACKUP_MD5={md5(cur_backup)}\nNEW_PRIMARY_MD5={md5(primary_img)}\nNEW_BACKUP_MD5={md5(backup_img)}\nDISK_SECTORS512={(ph['bak']+1)*8}\n")
