#!/usr/bin/env python3
"""Prefetch + persist benchmark tokenizers into the HF hub cache on yote.

Only tokenizer files are downloaded (KBs each), never model weights.
bench.sh passes --tokenizer kind=huggingface_auto,model=<repo-id> to GuideLLM,
which resolves through transformers' HF cache first -- so after this warm,
benchmark runs no longer depend on per-run Hub downloads.

Writes a verification manifest to bench/tokenizer-manifest.json
Run on yote: python3 scripts/prefetch-tokenizers.py
"""
import json
import os
from huggingface_hub import snapshot_download

REPOS = [
    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4",
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16",
    "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4",
    "mistralai/Mistral-Nemo-Instruct-2407",
    "mistralai/Codestral-22B-v0.1",
    "mistralai/Ministral-3-8B-Instruct-2512",
    "mistralai/Ministral-3-3B-Instruct-2512",
    "mistralai/Ministral-3-14B-Instruct-2512",
    "nvidia/Gemma-4-26B-A4B-NVFP4",
    "nex-agi/Nex-N2.5-mini",
    "nex-agi/Nex-N2.5-Pro",
    "LGAI-EXAONE/EXAONE-4.0-1.2B",
]

PATTERNS = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
    "tokenizer.model",
    "spiece.model",
    "sentencepiece.bpe.model",
    "chat_template.jinja",
]


def is_usable(files):
    names = set(files)
    return (
        "tokenizer.json" in names
        or ({"vocab.json", "merges.txt"} <= names)
        or any(n.endswith(".model") for n in names)
    )


manifest = {}
for repo in REPOS:
    try:
        path = snapshot_download(repo_id=repo, allow_patterns=PATTERNS)
        files = sorted(os.listdir(path))
        usable = is_usable(files)
        manifest[repo] = {
            "path": path,
            "files": files,
            "usable": usable,
            "error": None,
        }
        print(f"OK   {repo} usable={usable} files={len(files)}", flush=True)
    except Exception as e:  # fail-fast per repo, never abort the whole warm
        manifest[repo] = {
            "path": None,
            "files": [],
            "usable": False,
            "error": f"{type(e).__name__}: {e}",
        }
        print(f"FAIL {repo}: {type(e).__name__}: {e}", flush=True)

out = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "bench", "tokenizer-manifest.json"
)
with open(out, "w") as f:
    json.dump(manifest, f, indent=1)
n_ok = sum(1 for v in manifest.values() if v["usable"])
print(f"MANIFEST {out} usable={n_ok}/{len(REPOS)}")
