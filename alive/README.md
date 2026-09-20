# alive/ — endpoint-alive model lists

One model id per line, generated from the 2026-09-20 endpoint sweep
(`results/` + the sweep JSONL on yote). A model lands here only if a **live
request to a real completions endpoint** returned a verdict of `alive`
(HTTP 200 with generated tokens, including reasoning-only generations).

- `nvidia.txt` — 12 NVIDIA NIM models (OpenAI-compatible chat route)
- `mistral.txt` — 12 Mistral La Plateforme models
- `gemini.txt` — 1 Google model (generateContent route)
- `openrouter.txt` — 6 OpenRouter routes (OpenAI-compatible)
- `herd.txt` — 5 local herd GGUF quants (beellama/exaone-4-0-1-2b)
- `pollinations.txt` — 1 Pollinations text route
- `queue-gated.txt` — `moonshotai/kimi-k3`: endpoint-live but capacity-starved
  (see docs/FINDINGS.md). Kept separate so latency-sensitive consumers don't
  trip over a 150s queue wait.

Not here: quota-gated, auth-gated, entitlement-gated (kimi-k2.6), retired,
dead, or flaky verdicts. See `scripts/prober.py` for the verdict taxonomy
and `docs/FINDINGS.md` for what the edge cases mean.

---
## Estate docs

- **Fleet knowledgebase** — the canonical estate map, active crews, repo index,
  standing rules, and docs index (source of truth; this README does not
  duplicate it):
  <https://github.com/toxicwind/sovereign-projects/blob/main/docs/fleet-knowledgebase.md>
- **Master README** — the doc-graph root:
  <https://github.com/toxicwind/sovereign-projects/blob/main/README.md>
