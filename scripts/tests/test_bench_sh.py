"""bench.sh tokenizer-spec integration test."""
import os
import re
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def dry_run(*args):
    env = dict(os.environ)
    p = subprocess.run(
        [os.path.join(REPO, "bench.sh"), "--dry-run", *args],
        capture_output=True, text=True, env=env, cwd=REPO,
    )
    assert p.returncode == 0, p.stderr[-500:]
    return p.stdout


def backend_specs(out):
    # guidellm renders the tokenizer spec with \, escapes
    return re.findall(r"kind=huggingface_auto\\,model=([^ ]+)", out)


def test_ministral_tokenizer_carries_fix_mistral_regex():
    specs = backend_specs(dry_run("--provider", "mistral", "ministral-8b-2512"))
    assert specs, "no tokenizer specs emitted"
    assert all("load_kwargs.fix_mistral_regex=true" in s for s in specs), specs


def test_non_ministral_tokenizer_has_no_load_kwargs():
    specs = backend_specs(dry_run("--provider", "mistral", "codestral-2508"))
    assert specs, "no tokenizer specs emitted"
    assert all("load_kwargs" not in s for s in specs), specs


def test_strict_compat_backend_flag():
    out = dry_run("--provider", "mistral", "ministral-3b-2512")
    assert "openai_strict_compat=true" in out
    out = dry_run("--provider", "gemini", "gemma-4")
    assert "request_format=/chat/completions" in out
    assert "openai_strict_compat=true" in out
    out = dry_run("--provider", "nvidia", "nemotron-3-super")
    assert "openai_strict_compat" not in out
    assert "request_format=/v1/chat/completions" in out
