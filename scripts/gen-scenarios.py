#!/usr/bin/env python3
"""gen-scenarios.py — generate per-model GuideLLM scenario files.

Reads bench/models-bench.json (the general-chat benchmark set) and
context-map.json (per-model max context, built by ctx-mapper, source-
grounded 2026-09-20), and writes scenario JSONs into bench/scenarios/.

The scenario holds data/profile/constraints only. bench.sh supplies the
--backend (with the provider API key) and --tokenizer on the command line,
so no secrets ever land in these files.

Context sizing rules (from context-map.json + card reality):
- EFFECTIVE_CONTEXT_OVERRIDES: nemotron-3-super-120b-a12b and
  nemotron-3-ultra-550b-a55b advertise "up to 1M" but their NIM cards say
  "Defaults to 256k" — 1M needs VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 plus an
  explicit --max-model-len, i.e. it is NOT the served default. Size all
  GuideLLM runs at 256k for these two.
- Models with max_context null (e.g. mistral-code-fim-latest) get
  "max_context": null in metadata — unknown, do not size up.
- prompt+output targets are kept under 5% of the effective context.
- "provisional" context entries are flagged in metadata, not silently used.
- Models with effective context >= 128k also get a <slug>-long.json
  variant (8k prompt / 1k output) for long-context runs (bench.sh --long).
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
LONG_PROMPT_TOKENS = 8192
LONG_OUTPUT_TOKENS = 1024
LONG_CTX_THRESHOLD = 131072  # 128k: only models at/above get a -long variant
MAX_REQUESTS = 50
MAX_DURATION_S = 1800
MAX_ERRORS = 10
CTX_FRACTION = 0.05  # keep prompt+output under 5% of the effective context

# Served-default context, not marketing maximum. Both cards say "Up to 1M"
# but "Defaults to 256k"; the 1M figure needs VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
# + explicit --max-model-len and is not what the endpoint serves by default.
EFFECTIVE_CONTEXT_OVERRIDES = {
    "nvidia/nemotron-3-ultra-550b-a55b": 262144,
    "nvidia/nemotron-3-super-120b-a12b": 262144,
    "nvidia/nemotron-3-ultra-550b-a55b:free": 262144,
}


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


def ctx_info(model_id, ctx):
    """Return (advertised, effective, provisional, source, note)."""
    entry = ctx.get(model_id)
    if not isinstance(entry, dict):
        return None, None, False, None, "no context-map entry"
    advertised = entry.get("max_context")
    effective = EFFECTIVE_CONTEXT_OVERRIDES.get(model_id, advertised)
    return (
        advertised,
        effective,
        bool(entry.get("provisional")),
        entry.get("source"),
        entry.get("note"),
    )


def fit_tokens(prompt, output, effective):
    """Scale prompt/output down so their sum stays under CTX_FRACTION of
    the effective context. Returns (prompt, output, scaled)."""
    if not effective:
        return prompt, output, False
    budget = int(effective * CTX_FRACTION)
    if prompt + output <= budget:
        return prompt, output, False
    scale = budget / (prompt + output)
    return max(64, int(prompt * scale)), max(64, int(output * scale)), True


def make_scenario(entry, providers, ctx_meta, prompt_tokens, output_tokens,
                  scaled, variant):
    model_id = entry["id"]
    provider = entry["provider"]
    p = providers[provider]
    return {
        "benchmarks": [{}],
        "metadata": {
            "name": f"general-chat-{safe(model_id)}"
                    + ("-long" if variant == "long" else ""),
            "description": (
                f"General-chat benchmark ({variant}): {model_id} on {provider} "
                f"({prompt_tokens} prompt / {output_tokens} output tokens, "
                f"synchronous, {MAX_REQUESTS} requests)."
            ),
            "model": model_id,
            "provider": provider,
            "variant": variant,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "tokens_scaled_to_context": scaled,
            "max_context_advertised": ctx_meta["advertised"],
            "context_effective": ctx_meta["effective"],
            "context_provisional": ctx_meta["provisional"],
            "context_source": ctx_meta["source"],
            "context_note": ctx_meta["note"],
            "tokenizer": entry.get("tokenizer"),
            "tokenizer_verified": entry.get("tokenizer_verified", False),
        },
        "spec": {
            "backend": {
                "kind": "openai_http",
                "target": p["target"],
                "request_format": p["request_format"],
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
    n_std = n_long = 0
    for entry in bench["models"]:
        model_id = entry["id"]
        advertised, effective, provisional, source, note = ctx_info(model_id, ctx)
        ctx_meta = {
            "advertised": advertised,
            "effective": effective,
            "provisional": provisional,
            "source": source,
            "note": note,
        }
        prompt, output, scaled = fit_tokens(PROMPT_TOKENS, OUTPUT_TOKENS, effective)
        scen = make_scenario(entry, bench["providers"], ctx_meta,
                             prompt, output, scaled, "standard")
        with open(os.path.join(SCEN_DIR, safe(model_id) + ".json"), "w") as f:
            json.dump(scen, f, indent=2)
            f.write("\n")
        n_std += 1

        if effective and effective >= LONG_CTX_THRESHOLD:
            lprompt, loutput, lscaled = fit_tokens(
                LONG_PROMPT_TOKENS, LONG_OUTPUT_TOKENS, effective)
            long_scen = make_scenario(entry, bench["providers"], ctx_meta,
                                      lprompt, loutput, lscaled, "long")
            with open(os.path.join(SCEN_DIR, safe(model_id) + "-long.json"), "w") as f:
                json.dump(long_scen, f, indent=2)
                f.write("\n")
            n_long += 1
    print(f"wrote {n_std} standard + {n_long} long scenarios -> {SCEN_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
