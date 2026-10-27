# Compare two register dumps from t6050_phy_power_test.py (dump:NAME).
# usage: diff_dumps.py OLD.json NEW.json
import json, sys

CORE, PWR, DRD, AXI = 0x2ab000000, 0x2ab200000, 0x2aa280000, 0x2a8000000

def label(a):
    if PWR <= a < PWR + 0x1000:
        return f"pwr+{a - PWR:#x}"
    if CORE <= a < CORE + 0x300000:
        return f"core+{a - CORE:#x}"
    if DRD <= a < DRD + 0x10000:
        return f"drd+{a - DRD:#x}"
    if AXI <= a < AXI + 0x40000:
        return f"axi2af+{a - AXI:#x}"
    return hex(a)

old = json.load(open(sys.argv[1]))
new = json.load(open(sys.argv[2]))
only_new = sorted(int(a, 16) for a in new if a not in old)
changed = []
for a in sorted(set(old) & set(new), key=lambda x: int(x, 16)):
    if old[a] != new[a]:
        changed.append((int(a, 16), old[a], new[a]))
print(f"{len(changed)} changed of {len(set(old) & set(new))} common words; {len(only_new)} only in new")
for a, o, n in changed:
    if o is None or n is None:
        print(f"  {label(a):18} {o} -> {n}")
    else:
        print(f"  {label(a):18} {o:#010x} -> {n:#010x}  set {n & ~o:#x} cleared {o & ~n:#x}")
