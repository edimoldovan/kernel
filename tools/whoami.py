# Asks the connected proxy which loader it is.
from m1n1.setup import *
try:
    print("build tag:", p.get_build_tag() if hasattr(p, "get_build_tag") else "n/a")
except Exception as e:
    print("build tag error:", e)
print("base: %#x" % p.get_base())
