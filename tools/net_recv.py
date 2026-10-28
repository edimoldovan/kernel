#!/usr/bin/env python3
# net_recv.py OUT WAIT_S: accept one TCP connection on port 8000 from 192.168.188.0/24 (the
# J714c's network report, see TEST-LOOP.md), save the bytes to OUT. Runs nothing it receives.
import socket, sys
out, wait = sys.argv[1], int(sys.argv[2])
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 8000)); s.listen(1); s.settimeout(wait)
while True:
    c, a = s.accept()
    if a[0].startswith('192.168.188.'):
        break
    c.close()
c.settimeout(60); data = b''
while True:
    b = c.recv(65536)
    if not b:
        break
    data += b
open(out, 'wb').write(data)
print(f"from {a[0]}: {len(data)} bytes")
