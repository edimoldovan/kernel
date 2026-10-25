# mkdtb.py <out.dtb> <name>[,name...]  : from new.dts, mark the named domains firmware-owned (read-only for the driver), build the dtb.
import re, sys, subprocess
S = sys.argv[0].rsplit("/", 1)[0]; out = sys.argv[1]; names = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else set()
t = open(S + "/new.dts").read(); hit = set()
def fix(m):
    body = m.group(0); lab = re.search(r'label = "([a-z0-9_]+)"', body).group(1)
    if lab in names and "apple,firmware-owned" not in body:
        hit.add(lab); body = body.replace("\n\t\t\t};", "\n\t\t\t\tapple,firmware-owned;\n\t\t\t};", 1)
    return body
t2 = re.sub(r"\t\t\tpower-controller@[0-9a-f]+ \{\n(?:\t\t\t\t[^\n]*\n)*?\t\t\t\};", fix, t)
open(out + ".dts", "w").write(t2); subprocess.check_call(["dtc", "-q", "-I", "dts", "-O", "dtb", "-o", out, out + ".dts"])
print("firmware-owned total:", t2.count("apple,firmware-owned"), "| newly marked:", len(hit), "| not found:", sorted(names - hit))
