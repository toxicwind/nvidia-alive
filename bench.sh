#!/usr/bin/env bash
# bench.sh — GuideLLM sweep over NVIDIA alive-filtered models.
#
# Reads the alive filter (one model id per line):
#   ~/.local/share/nvidia-alive/models-alive.txt
# produced by prober.py. Benchmarks each alive model on the NVIDIA
# provider with the smoke scenario (override SCENARIO for bigger runs).
#
# Needs NVIDIA_API_KEY in the environment:
#   set -a; . ~/.secrets; set +a; ./bench.sh [model-substring]
#
# Optional arg filters models by substring (e.g. ./bench.sh nemotron).
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
ALIVE="$HOME/.local/share/nvidia-alive/models-alive.txt"
OUT="$HOME/.local/share/nvidia-alive/bench"
SCENARIO="${SCENARIO:-$DIR/scenario-smoke.json}"
FILTER="${1:-}"

if [ -z "${NVIDIA_API_KEY:-}" ]; then
  echo "NVIDIA_API_KEY not set" >&2
  exit 2
fi
if [ ! -f "$ALIVE" ]; then
  echo "alive list missing: $ALIVE (run prober.py first)" >&2
  exit 2
fi
mkdir -p "$OUT"

count=0
while IFS= read -r model; do
  [ -z "$model" ] && continue
  if [ -n "$FILTER" ]; then
    case "$model" in
      *"$FILTER"*) ;;
      *) continue ;;
    esac
  fi
  safe="$(printf '%s' "$model" | tr '/:' '__')"
  echo "=== $model"
  guidellm run --config "$SCENARIO" \
    --backend "kind=openai_http,target=https://integrate.api.nvidia.com,model=$model,api_key=$NVIDIA_API_KEY" \
    --output "kind=json,path=$OUT/$safe.json" \
    --disable-console-interactive || echo "FAILED: $model"
  count=$((count + 1))
done < "$ALIVE"
echo "swept $count models -> $OUT"
