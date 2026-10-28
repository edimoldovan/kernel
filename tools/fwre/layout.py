# layout.py RUST_FILE STRUCT READS_FILE TAG: lay out a packed Rust struct and check each firmware read
import re, sys
src = open(sys.argv[1]).read(); name = sys.argv[2]
consts = {k: int(v, 0) for k, v in re.findall(r'const (\w+): usize = (0x[0-9a-f]+|\d+);', src)}
sizes = {'u8': 1, 'u16': 2, 'u32': 4, 'u64': 8, 'i32': 4, 'RegisterMapEntry': 0x28, 'PerfGroup': 0x704,
         'CompletionRingDescriptor': 0x20, 'ChannelEntry': 0x20, 'LevelDescriptor': 0x20}
def tsize(t):
    t = t.strip()
    m = re.fullmatch(r'\[(.+);\s*(\w+)\]', t)
    if m:
        n = m.group(2); n = int(n, 0) if n[0].isdigit() else consts[n]
        return tsize(m.group(1)) * n
    return sizes[t]
body = re.search(r'pub\(crate\) struct ' + name + r' \{(.*?)\n\}', src, re.S).group(1)
fields, off = [], 0
for fname, ftype in re.findall(r'pub\(crate\) (\w+): ([^,\n]+),', body):
    s = tsize(ftype); scalar = not ftype.startswith('[') or ftype.startswith('[u8')
    fields.append((off, s, fname, ftype.strip()))
    m = re.fullmatch(r'unk_([0-9a-f]+)', fname)
    if m and int(m.group(1), 16) != off: print(f"name/offset mismatch {fname} at {off:#x}")
    off += s
print(f"{name}: {off:#x} bytes, {len(fields)} fields")
def field_at(a):
    for f in fields:
        if f[0] <= a < f[0] + f[1]: return f
for line in open(sys.argv[3]):
    tag, a, w, kind, at = line.split()
    if tag != sys.argv[4]: continue
    a = int(a, 16); w = int(w)
    f = field_at(a); g = field_at(a + w - 1)
    if f is None: print(f"{a:#06x}/{w} {kind} at {at}: beyond the struct"); continue
    note = ""
    if f is not g: note = f"spans {f[2]} and {g[2] if g else 'end'}"
    elif not f[3].startswith('[u8') and f[3] in sizes and (a != f[0] or w != f[1]): note = f"inside {f[2]} ({f[3]})"
    if note: print(f"{a:#06x}/{w} {kind} at {at}: {note}")
