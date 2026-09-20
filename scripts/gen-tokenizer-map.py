#!/usr/bin/env python3
"""Regenerate bench/tokenizer-map.json from bench/models-bench.json.

models-bench.json is the single authoritative source (bench.sh reads it).
tokenizer-map.json is a DERIVED artifact: a human-readable NIM-ID -> HF
tokenizer reference with verification notes. Never edit it by hand --
edit models-bench.json and re-run this.
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(BASE, "bench", "models-bench.json")
OUT = os.path.join(BASE, "bench", "tokenizer-map.json")

NOTES = {
    "nvidia/nemotron-3-ultra-550b-a55b": (
        "NIM card names HF repo nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4; "
        "tokenizer_config.json HTTP 200."
    ),
    "nvidia/nemotron-3-super-120b-a12b": (
        "NIM card links the BF16 repo; tokenizer files identical across BF16/NVFP4 quants."
    ),
    "nvidia/nemotron-3.5-lightning-30b-a3b": (
        "NIM card names HF repo nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4."
    ),
    "mistralai/mistral-nemotron": (
        "PROVISIONAL family match: NIM card names no HF repo; mistral-nemotron is the "
        "Mistral NeMo 12B family (Tekken tokenizer). Canonical repo unpublished."
    ),
    "ministral-3b-2512": "Public ungated repo mistralai/Ministral-3-3B-Instruct-2512; tokenizer.json present.",
    "ministral-3b-latest": "Alias of ministral-3b-2512.",
    "ministral-8b-2512": "Public ungated repo mistralai/Ministral-3-8B-Instruct-2512; tokenizer.json present.",
    "ministral-8b-latest": "Alias of ministral-8b-2512.",
    "ministral-14b-2512": "Public ungated repo mistralai/Ministral-3-14B-Instruct-2512; tokenizer.json present.",
    "ministral-14b-latest": "Alias of ministral-14b-2512.",
    "codestral-2508": (
        "PROVISIONAL family match: no canonical repo published for codestral-2508; "
        "using public mistralai/Codestral-22B-v0.1 tokenizer (same family)."
    ),
    "codestral-latest": "Alias of codestral-2508 (provisional family match).",
    "mistral-code-latest": "Alias of codestral-2508 (provisional family match).",
    "mistral-code-fim-latest": "Alias of codestral-2508 (provisional family match).",
    "gemma-4-26b-a4b-it": (
        "Usable quant: NVIDIA public NVFP4 repo nvidia/Gemma-4-26B-A4B-NVFP4; "
        "canonical Google source repo not published for this NIM id."
    ),
    "nex-agi/nex-n2.5-mini:free": "Exact case-sensitive repo nex-agi/Nex-N2.5-mini verified live.",
    "nex-agi/nex-n2.5-pro:free": "Exact case-sensitive repo nex-agi/Nex-N2.5-Pro verified live.",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "Same tokenizer as nvidia/nemotron-3-ultra-550b-a55b.",
    "nvidia/nemotron-3.5-lightning:free": "Same tokenizer as nvidia/nemotron-3.5-lightning-30b-a3b.",
    "beellama/exaone-4-0-1-2b:iq4xs": "LGAI-EXAONE/EXAONE-4.0-1.2B verified live; shared across all five herd quants.",
    "beellama/exaone-4-0-1-2b:q4km": "Same tokenizer as beellama/exaone-4-0-1-2b:iq4xs.",
    "beellama/exaone-4-0-1-2b:q5km": "Same tokenizer as beellama/exaone-4-0-1-2b:iq4xs.",
    "beellama/exaone-4-0-1-2b:q6k": "Same tokenizer as beellama/exaone-4-0-1-2b:iq4xs.",
    "beellama/exaone-4-0-1-2b:q80": "Same tokenizer as beellama/exaone-4-0-1-2b:iq4xs.",
}

with open(MODELS) as f:
    data = json.load(f)
models = data["models"] if isinstance(data, dict) else data

out = {
    "_meta": {
        "derived_from": "bench/models-bench.json",
        "generated": "2026-09-20",
        "note": (
            "DERIVED ARTIFACT -- do not edit by hand. models-bench.json is the "
            "single authoritative mapping consumed by bench.sh. verified=false "
            "means provisional family match (see note)."
        ),
    }
}
for m in models:
    mid = m["id"]
    out[mid] = {
        "tokenizer": m.get("tokenizer", ""),
        "verified": bool(m.get("tokenizer_verified")),
        "note": NOTES.get(mid, ""),
    }

with open(OUT, "w") as f:
    json.dump(out, f, indent=1)
    f.write("\n")
print(f"wrote {OUT} with {len(models)} entries")
