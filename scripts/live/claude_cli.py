"""claude_cli.py — Run one headless Claude Code session (`claude -p`) and return its text.

Shared by salary lookups (web tools on) and LinkedIn post checks (no tools). Logged
in through CLAUDE_CODE_OAUTH_TOKEN (the owner's Claude subscription) in the
workflow, or the local `claude` login. Runs in an empty temp dir; only the tools
passed in exist in the session, pre-approved, and anything else is refused.
"""
import json
import re
import shutil
import subprocess
import tempfile


class QuotaExceeded(Exception):
    """Subscription usage / rate limit reached — try again on a later run."""


class BadRequest(Exception):
    """Can't work as configured (not logged in, CLI missing) — retrying won't help."""


_LIMIT_HINTS = ("usage limit", "rate limit", "rate_limit", "overloaded", "429", "quota")
_AUTH_HINTS = ("invalid api key", "please run /login", "not logged in", "authentication",
               "oauth", "401", "403")


def run(prompt, cfg, tools=()):
    """Claude's final text answer. Raises QuotaExceeded / BadRequest / RuntimeError."""
    exe = shutil.which(cfg.get("claude_bin", "claude"))
    if not exe:
        raise BadRequest("claude CLI not found (npm install -g @anthropic-ai/claude-code)")
    names = ",".join(tools)
    cmd = [exe, "-p", prompt, "--output-format", "json", "--tools", names,
           "--permission-mode", "dontAsk", "--model", cfg.get("model", "sonnet"),
           # no MCP servers / connectors from the user's own Claude setup
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    if names:
        cmd += ["--allowedTools", names]
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                              timeout=cfg.get("timeout_sec", 300))
    raw = (proc.stdout or "").strip()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {"is_error": True, "result": raw or proc.stderr}
    text = str(data.get("result") or "")
    if data.get("is_error") or proc.returncode != 0:
        low = (text + " " + (proc.stderr or "")).lower()
        msg = (text or proc.stderr or "").strip()[:300]
        if any(h in low for h in _LIMIT_HINTS):
            raise QuotaExceeded(msg)
        if any(h in low for h in _AUTH_HINTS):
            raise BadRequest(msg)
        raise RuntimeError(msg or f"claude exited {proc.returncode}")
    if data.get("permission_denials"):
        raise BadRequest(f"a tool was not permitted: {data['permission_denials'][:1]}")
    return text


def json_array(text):
    """The first JSON array of objects in Claude's answer ([] if none)."""
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict)]
