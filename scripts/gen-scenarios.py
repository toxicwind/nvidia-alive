#!/usr/bin/env python3
"""gen-scenarios.py — generate per-model GuideLLM scenario files.

Reads bench/models-bench.json (the general-chat benchmark set) and the
optional context-map.json (per-model max context, built by ctx-mapper),
and writes one scenario JSON per model into bench/scenarios/.

The scenario holds data/profile/constraints only. bench.sh supplies the
--backend (with the provider API key) and --tokenizer on the command line,
so no secrets ever land in these files.

Context wiring: scenario prompt/output token targets are checked against
the model's max context when context-map.json is present; targets are
scaled down if they would exceed 5% of the context window.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "bench")
MODELS_FILE = os.path.join(BENCH, "models-bench.json")
CTX_CANDIDATES = [
    os.path.join(ROOT, "context-map.json"),      # ctx-mapper's drop point
    os.path.join(BENCH, "context-map.json"),     # alternate
]
SCEN_DIR = os.path.join(BENCH, "scenarios")

PROMPT_TOKENS = 1024
OUTPUT_TOKENS = 512
MAX_REQUESTS = 50
MAX_DURATION_S = 1800
MAX_ERRORS = 10
CTX_FRACTION = 0.05  # keep prompt+output under 5% of the context window


def safe(model_id: str) -> str:
    return model_id.replace("/", "__").replace(":", "__")


def load_context_map():
    for path in CTX_CANDIDATES:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            print(f"context-map: using {path} ({len(data)} entries)", file=sys.stderr)
            return data
    print("context-map: not found, scenarios use default token targets", file=sys.stderr)
    return {}


def scenario_for(entry, providers, ctx):
    model_id = entry["id"]
    provider = entry["provider"]
    target = providers[provider]["target"]
    request_format = providers[provider]["request_format"]

    prompt_tokens, output_tokens = PROMPT_TOKENS, OUTPUT_TOKENS
    max_context = None
    if model_id in ctx and isinstance(ctx[model_id], dict):
        max_context = ctx[model_id].get("max_context")
    if max_context:
        budget = int(max_context * CTX_FRACTION)
        if prompt_tokens + output_tokens > budget:
            scale = budget / (prompt_tokens + output_tokens)
            prompt_tokens = max(64, int(prompt_tokens * scale))
            output_tokens = max(64, int(output_tokens * scale))

    return {
        "benchmarks": [{}],
        "metadata": {
            "name": f"general-chat-{safe(model_id)}",
            "description": (
                f"General-chat benchmark: {model_id} on {provider} "
                f"({prompt_tokens} prompt / {output_tokens} output tokens, "
                f"synchronous, {MAX_REQUESTS} requests)."
            ),
            "model": model_id,
            "provider": provider,
            "max_context": max_context,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "tokenizer": entry.get("tokenizer"),
            "tokenizer_verified": entry.get("tokenizer_verified", False),
        },
        "spec": {
            "backend": {
                "kind": "openai_http",
                "target": target,
                "request_format": request_format,
                # model + api_key are injected by bench.sh on the CLI
            },
            "data": [
                {
                    "kind": "synthetic_text",
                    "prompt_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                }
            ],
            "profile": {"kind": "synchronous"},
            "constraints": [
                {"kind": "max_requests", "count": MAX_REQUESTS},
                {"kind": "max_duration", "seconds": MAX_DURATION_S},
                {"kind": "max_errors", "count": MAX_ERRORS},
            ],
        },
    }


def main() -> int:
    with open(MODELS_FILE) as f:
        bench = json.load(f)
    ctx = load_context_map()
    os.makedirs(SCEN_DIR, exist_ok=True)
    n = 0
    for entry in bench["models"]:
        scen = scenario_for(entry, bench["providers"], ctx)
        path = os.path.join(SCEN_DIR, safe(entry["id"]) + ".json")
        with open(path, "w") as f:
            json.dump(scen, f, indent=2)
            f.write("\n")
        n += 1
    print(f"wrote {n} scenarios -> {SCEN_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
