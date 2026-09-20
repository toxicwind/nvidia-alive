#!/bin/bash
# k3-runner.sh [label]: one pcap'd kimi-k3 timing run. Self-contained: starts
# tcpdump, runs the instrumented probe once, stops tcpdump, drops a done marker.
# Launched with nohup from the bridge; never run interactively.
LABEL=${1:-k3-pcap}
set -a; . ~/.secrets >/dev/null 2>&1; set +a
IPS=$(getent hosts integrate.api.nvidia.com | cut -d' ' -f1)
FILTER=""
for ip in $IPS; do
  if [ -z "$FILTER" ]; then FILTER="host $ip"; else FILTER="$FILTER or host $ip"; fi
done
FILTER="( $FILTER ) and port 443"
echo "pcap filter: $FILTER" >> /tmp/k3-runner.log
sudo /usr/sbin/tcpdump -i any -w /tmp/k3.pcap "$FILTER" >> /tmp/k3-runner.log 2>&1 &
TPID=$!
sleep 1
python3 /home/toxic/nvidia-alive/kimi-k3-timing.py \
  /home/toxic/.local/share/nvidia-alive/k3-timing.jsonl \
  moonshotai/kimi-k3 "$LABEL" 1 >> /tmp/k3-runner.log 2>&1
sudo kill -INT $TPID 2>/dev/null
wait $TPID 2>/dev/null
echo DONE > /tmp/k3-runner.done
echo "runner finished ($LABEL)" >> /tmp/k3-runner.log
