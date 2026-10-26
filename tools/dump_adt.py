# Dumps the whole Apple device tree of the connected proxy as text.
import sys
from m1n1.setup import *
sys.stdout.write(str(u.adt))
