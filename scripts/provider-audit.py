#!/usr/bin/env python3
"""Full LLM-provider audit: every provider key in .secrets -> its models endpoint.
Reports HTTP status, total model count, and *kimi* matches.
Keys come from the environment only; only names/statuses/IDs are printed.
"""
import json
import os
import urllib.error
import urllib.request

K = os.environ


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, str(e)[:120])


def model_ids(payload):
    try:
        d = json.loads(payload)
    except Exception:
        return None
    if isinstance(d, dict):
        data = d.get("data") or d.get("models") or []
    elif isinstance(d, list):
        data = d
    else:
        data = []
    out = []
    for m in data:
        if isinstance(m, dict):
            mid = m.get("id") or m.get("name") or ""
            mid = str(mid).replace("models/", "")
        else:
            mid = str(m)
        if mid:
            out.append(mid)
    return out


def bearer(envname):
    v = K.get(envname, "")
    return {"Authorization": "Bearer " + v} if v else {}


def audit(name, url, headers, envnames=()):
    missing = [e for e in envnames if not K.get(e)]
    if missing:
        print("### %s: SKIP (unset in env: %s)" % (name, ",".join(missing)))
        return
    status, body = get(url, headers)
    ids = model_ids(body)
    if ids is None:
        print("### %s: http=%s total=? (unparseable body)" % (name, status))
        return
    kimi = [i for i in ids if "kimi" in i.lower()]
    print("### %s: http=%s total=%d kimi=%d" % (name, status, len(ids), len(kimi)))
    for i in kimi:
        print("   -", i)


def audit_multi(name, urls, headers, envnames=()):
    """Try urls in order; report the first that returns parseable model IDs."""
    missing = [e for e in envnames if not K.get(e)]
    if missing:
        print("### %s: SKIP (unset in env: %s)" % (name, ",".join(missing)))
        return
    for url in urls:
        status, body = get(url, headers)
        ids = model_ids(body)
        if ids is not None and (status == 200 or ids):
            kimi = [i for i in ids if "kimi" in i.lower()]
            print("### %s: http=%s total=%d kimi=%d [%s]"
                  % (name, status, len(ids), len(kimi), url))
            for i in kimi:
                print("   -", i)
            return
    print("### %s: all endpoints failed" % name)


print("== provider audit ==")
audit("anthropic", "https://api.anthropic.com/v1/models",
      {"x-api-key": K.get("ANTHROPIC_API_KEY", ""),
       "anthropic-version": "2023-06-01"},
      ("ANTHROPIC_API_KEY",))
audit("cerebras", "https://api.cerebras.ai/v1/models",
      bearer("CEREBRAS_API_KEY"), ("CEREBRAS_API_KEY",))
audit_multi("deepseek",
            ["https://api.deepseek.com/models",
             "https://api.deepseek.com/v1/models"],
            bearer("DEEPSEEK_API_KEY"), ("DEEPSEEK_API_KEY",))
audit("groq", "https://api.groq.com/openai/v1/models",
      bearer("GROQ_API_KEY"), ("GROQ_API_KEY",))
audit("mistral", "https://api.mistral.ai/v1/models",
      bearer("MISTRAL_API_KEY"), ("MISTRAL_API_KEY",))

for envname in ["GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2",
                "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5",
                "GOOGLE_API_KEY"]:
    key = K.get(envname, "")
    if not key:
        print("### gemini[%s]: SKIP (unset)" % envname)
        continue
    status, body = get(
        "https://generativelanguage.googleapis.com/v1beta/models?key=" + key)
    ids = model_ids(body)
    if ids is None:
        print("### gemini[%s]: http=%s (unparseable)" % (envname, status))
    else:
        kimi = [i for i in ids if "kimi" in i.lower()]
        print("### gemini[%s]: http=%s total=%d kimi=%d"
              % (envname, status, len(ids), len(kimi)))

audit("moonshot", "https://api.moonshot.ai/v1/models",
      bearer("MOONSHOT_API_KEY"), ("MOONSHOT_API_KEY",))
audit("nvidia[NVIDIA_API_KEY]", "https://integrate.api.nvidia.com/v1/models",
      bearer("NVIDIA_API_KEY"), ("NVIDIA_API_KEY",))
audit("nvidia[NIM_API_KEY]", "https://integrate.api.nvidia.com/v1/models",
      bearer("NIM_API_KEY"), ("NIM_API_KEY",))
audit("nvidia[NVIDIA_NIM_API_KEY]", "https://integrate.api.nvidia.com/v1/models",
      bearer("NVIDIA_NIM_API_KEY"), ("NVIDIA_NIM_API_KEY",))
audit("nvidia[NVIDIA_NIM_API_KEY_1]", "https://integrate.api.nvidia.com/v1/models",
      bearer("NVIDIA_NIM_API_KEY_1"), ("NVIDIA_NIM_API_KEY_1",))
audit("nvidia[NIM_PROXY_API_KEY]", "https://integrate.api.nvidia.com/v1/models",
      bearer("NIM_PROXY_API_KEY"), ("NIM_PROXY_API_KEY",))

multi = K.get("NVIDIA_API_KEYS", "")
if multi:
    for n, part in enumerate(multi.split(","), 1):
        part = part.strip().strip("'\"")
        if not part:
            continue
        status, body = get("https://integrate.api.nvidia.com/v1/models",
                           {"Authorization": "Bearer " + part})
        ids = model_ids(body)
        if ids is None:
            print("### nvidia[NVIDIA_API_KEYS#%d]: http=%s (unparseable)" % (n, status))
        else:
            kimi = [i for i in ids if "kimi" in i.lower()]
            print("### nvidia[NVIDIA_API_KEYS#%d]: http=%s total=%d kimi=%d"
                  % (n, status, len(ids), len(kimi)))
else:
    print("### nvidia[NVIDIA_API_KEYS]: SKIP (unset)")

audit("openrouter[OPENROUTER_API_KEY]", "https://openrouter.ai/api/v1/models",
      bearer("OPENROUTER_API_KEY"), ("OPENROUTER_API_KEY",))
audit("openrouter[OPENROUTER_API_KEY_1]", "https://openrouter.ai/api/v1/models",
      bearer("OPENROUTER_API_KEY_1"), ("OPENROUTER_API_KEY_1",))
audit("pollinations", "https://text.pollinations.ai/models", {})
audit("hf-router", "https://router.huggingface.co/v1/models",
      bearer("HF_TOKEN"), ("HF_TOKEN",))
audit("herd", "http://127.0.0.1:25100/v1/models", {})
audit("flock", "http://127.0.0.1:8000/v1/models",
      bearer("FLOCK_API_KEY"), ("FLOCK_API_KEY",))
print("== done ==")
