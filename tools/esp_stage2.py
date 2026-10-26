# Tells the stage 1 proxy to load aurora/stage2.bin from the EFI partition, as its own config would after the window.
from m1n1.setup import *
spec = "6790ddc4-e993-42c2-8135-807df1548aaf;aurora/stage2.bin"
print("boot_storage", spec)
try:
    print("ret", p.kboot_boot_storage(spec))
except Exception as e:
    print("proxy left:", type(e).__name__)
