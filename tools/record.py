"""Record raw pen reports forwarded by the running driver: python record.py SECONDS OUT.csv"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import socket, sys, time

secs, out = float(sys.argv[1]), sys.argv[2]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", 47812))
s.settimeout(0.5)
end = time.time() + secs
rows = []
while time.time() < end:
    try:
        r = s.recv(64)
    except OSError:
        continue
    if len(r) >= 8 and r[0] == 2:
        rows.append((time.perf_counter(), r[1] | r[2] << 8, r[3] | r[4] << 8, r[5], r[6] | r[7] << 8))
with open(out, "w") as f:
    f.write("t,x,y,st,p\n")
    for row in rows:
        f.write("%.5f,%d,%d,%d,%d\n" % row)
print(len(rows), "reports;", sum(1 for r in rows if r[3] & 4), "with tip down")
