#!/usr/bin/env python3
"""Analyze k3 pcap: per-10s traffic buckets by direction + max server-data gap."""
import subprocess
import sys
from collections import defaultdict

PCAP = sys.argv[1] if len(sys.argv) > 1 else "/tmp/k3.pcap"
CLIENT = "10.0.0.218"
PORT = sys.argv[2] if len(sys.argv) > 2 else None

fields = ["-e", "frame.time_relative", "-e", "ip.src", "-e", "tcp.len",
          "-e", "tcp.srcport", "-e", "tcp.dstport"]
filt = ("tcp.port==%s" % PORT) if PORT else None
cmd = ["tshark", "-r", PCAP]
if filt:
    cmd += ["-Y", filt]
cmd += ["-T", "fields"] + fields

out = subprocess.run(cmd, capture_output=True, text=True)
pkts = []
conns = {}
for line in out.stdout.splitlines():
    p = line.split("\t")
    if len(p) < 5:
        continue
    try:
        t, src, ln, sp, dp = float(p[0]), p[1], int(p[2] or 0), p[3], p[4]
    except ValueError:
        continue
    pkts.append((t, src, ln))
    key = (sp, dp) if src == CLIENT else (dp, sp)
    conns[key] = conns.get(key, 0) + 1
if not pkts:
    print("no packets parsed")
    sys.exit(1)
t0 = pkts[0][0]
print("packets: %d  span: %.1fs" % (len(pkts), pkts[-1][0] - t0))
if not PORT:
    print("connections (clientport, serverport): frames")
    for k, c in sorted(conns.items(), key=lambda x: -x[1])[:8]:
        print("  %s: %d" % (k, c))
buckets = defaultdict(lambda: [0, 0, 0, 0])
for t, src, ln in pkts:
    b = int((t - t0) // 10) * 10
    k = 0 if src == CLIENT else 2
    buckets[b][k] += 1
    buckets[b][k + 1] += ln
print("t_start | c2s pkts/bytes | s2c pkts/bytes")
for b in sorted(buckets):
    c2s_p, c2s_b, s2c_p, s2c_b = buckets[b]
    mark = "   <-- data" if (s2c_b > 2000 or c2s_b > 2000) else ""
    print(" %4ds  | %4d/%8d | %4d/%8d%s" % (b, c2s_p, c2s_b, s2c_p, s2c_b, mark))
s2c_times = [t for t, s, ln in pkts if s != CLIENT and ln > 0]
gaps = [b - a for a, b in zip(s2c_times, s2c_times[1:])]
print("server->client data packets: %d" % len(s2c_times))
print("max gap between server data packets: %.1fs" % (max(gaps) if gaps else 0))
# what are the 5 retrans/dupack frames?
out2 = subprocess.run(
    ["tshark", "-r", PCAP, "-Y",
     "tcp.analysis.retransmission or tcp.analysis.duplicate_ack",
     "-T", "fields", "-e", "frame.time_relative", "-e", "ip.src",
     "-e", "tcp.analysis.retransmission", "-e", "tcp.analysis.duplicate_ack"],
    capture_output=True, text=True)
print("retrans/dupack frames:")
for line in out2.stdout.splitlines()[:8]:
    print("  " + line.replace("\t", " | "))
