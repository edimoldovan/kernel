#!/usr/bin/env python3
# net_serve.py DIR UPLOADS SECONDS: HTTP on 192.168.188.35:8000 (the port the network reports use)
# for the J714c writer initramfs (initramfs/init-write-omarchy), clients in 192.168.188.0/24 only.
# GET /<file> sends DIR/<file>; POST /<name> saves the body as UPLOADS/<name>, never over an earlier
# upload (a second one becomes <name>.1 ...). Exits after POST /report, or after SECONDS.
import http.server
import ipaddress
import os
import sys
import threading
import time

DIR, UPLOADS, SECONDS = sys.argv[1], sys.argv[2], int(sys.argv[3])
NET = ipaddress.ip_network("192.168.188.0/24")
done = threading.Event()


def log(msg):
    print(f"{time.strftime('%T')} {msg}", flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def name(self):
        if ipaddress.ip_address(self.client_address[0]) not in NET:
            self.send_error(403)
            return None
        name = os.path.basename(self.path)
        if not name or name.startswith("."):
            self.send_error(404)
            return None
        return name

    def do_GET(self):
        name = self.name()
        if not name:
            return
        path = os.path.join(DIR, name)
        if not os.path.isfile(path):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(os.path.getsize(path)))
        self.end_headers()
        log(f"sending {name}")
        with open(path, "rb") as f:
            while block := f.read(1 << 20):
                self.wfile.write(block)
        log(f"sent {name}")

    def do_POST(self):
        name = self.name()
        if not name:
            return
        path, n = os.path.join(UPLOADS, name), 0
        while os.path.exists(path):
            n += 1
            path = os.path.join(UPLOADS, f"{name}.{n}")
        left = int(self.headers.get("Content-Length", 0))
        with open(path, "wb") as f:
            while left > 0:
                block = self.rfile.read(min(left, 1 << 20))
                if not block:
                    break
                f.write(block)
                left -= len(block)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()
        log(f"saved {os.path.basename(path)} ({os.path.getsize(path)} bytes)")
        if name == "report":
            done.set()

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("192.168.188.35", 8000), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
log(f"serving {DIR} for {SECONDS} s")
log("report received" if done.wait(SECONDS) else "timeout")
server.shutdown()
