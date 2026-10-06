#!/usr/bin/env python3
"""PreToolUse guard: refuse `gh` commands that would publish local environment
detail or secrets to GitHub.

Reads the Claude Code hook payload on stdin. Exit 0 = allow, exit 2 = deny
(stderr is fed back to the model so it rewrites).

Escape hatch: GH_HYGIENE=off in the environment.
"""
import json
import os
import re
import shlex
import sys

ALLOW, DENY = 0, 2

# gh subcommands that publish text other people will read.
PUBLISHING = {
    ("pr", "create"), ("pr", "comment"), ("pr", "edit"), ("pr", "review"),
    ("issue", "create"), ("issue", "comment"), ("issue", "edit"),
    ("release", "create"), ("release", "edit"),
    ("gist", "create"),
}

# Flags whose value is body text.
TEXT_FLAGS = {"--body", "-b", "--title", "-t", "--notes", "--message", "-m"}
# Flags whose value is a path to body text.
FILE_FLAGS = {"--body-file", "-F", "--notes-file", "--notes-from-tag"}

ENV_LEAKS = [
    (r"/home/[A-Za-z0-9_.\-]+", "absolute home path"),
    (r"/Users/[A-Za-z0-9_.\-]+", "absolute macOS home path"),
    (r"\$HOME\b", "$HOME"),
    (r"~/\.(claude|config|dotfiles|local|nvm|ssh|agents|pi)\b", "local dotfile path"),
    (r"\.claude/(plugins|skills|projects|settings|commands|agents)", "local Claude Code layout"),
    (r"skills-vendor", "local skills-vendor layout"),
    (r"/tmp/", "temp path"),
    (r"\.worktrees/", "local worktree layout"),
    (r"\b(AOE|AGENT_OF_EMPIRES|ANTHROPIC|CLAUDE_CODE)_[A-Z0-9_]+", "local environment variable"),
    (r"\baoe\s+(add|send|session|list|group|ps|remove|worktree)\b", "aoe tooling"),
    (r"\bagent-of-empires\b", "aoe tooling"),
    (r"\bagent-deck\b", "local agent tooling"),
    (r"\btmux\b", "local terminal tooling"),
    (r"\bcaprica\b", "machine hostname"),
    (r"\bon (my|this) machine\b", "environment narration"),
    (r"\bmy local\b", "environment narration"),
    (r"\bin my setup\b", "environment narration"),
    (r"\bmy install(ation)?\b", "environment narration"),
    (r"\blocally I\b", "environment narration"),
]

SECRETS = [
    (r"\bgh[pousr]_[A-Za-z0-9]{16,}", "GitHub token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained token"),
    (r"\bsk-ant-[A-Za-z0-9\-_]{16,}", "Anthropic API key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\bAUTH_TOKEN\s*[=:]\s*\S", "auth token assignment"),
    (r"\bxox[baprs]-[A-Za-z0-9\-]{10,}", "Slack token"),
]

HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def heredoc_bodies(raw):
    """Return (bodies, raw_without_heredocs)."""
    bodies, kept = [], []
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEREDOC_RE.search(line)
        kept.append(HEREDOC_RE.sub("", line) if m else line)
        i += 1
        if not m:
            continue
        term = m.group(2)
        buf = []
        while i < len(lines) and lines[i].strip() != term:
            buf.append(lines[i])
            i += 1
        i += 1  # skip terminator
        bodies.append("\n".join(buf))
    return bodies, "\n".join(kept)


def is_publishing(tokens):
    for i, tok in enumerate(tokens):
        if tok != "gh" and not tok.endswith("/gh"):
            continue
        rest = [t for t in tokens[i + 1:] if not t.startswith("-")]
        if len(rest) >= 2 and (rest[0], rest[1]) in PUBLISHING:
            return True
        # gh api POST/PATCH against comment-ish endpoints
        if rest and rest[0] == "api":
            tail = " ".join(tokens[i + 1:])
            if re.search(r"-X\s*(POST|PATCH|PUT)", tail) or "--method" in tail:
                if re.search(r"(issues|pulls|comments|reviews|releases)", tail):
                    return True
    return False


def collect_text(tokens, heredocs):
    """Body text to scan, and paths whose contents to scan."""
    chunks = list(heredocs)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in TEXT_FLAGS and i + 1 < len(tokens):
            chunks.append(tokens[i + 1])
            i += 2
            continue
        for flag in TEXT_FLAGS:
            if tok.startswith(flag + "="):
                chunks.append(tok[len(flag) + 1:])
        if tok in FILE_FLAGS and i + 1 < len(tokens):
            path = tokens[i + 1]
            if path != "-":
                try:
                    with open(os.path.expanduser(path), "r", errors="replace") as fh:
                        chunks.append(fh.read())
                except OSError:
                    pass
            i += 2
            continue
        for flag in FILE_FLAGS:
            if tok.startswith(flag + "="):
                path = tok[len(flag) + 1:]
                try:
                    with open(os.path.expanduser(path), "r", errors="replace") as fh:
                        chunks.append(fh.read())
                except OSError:
                    pass
        # gh api -f body=... / --field body=...
        if tok in ("-f", "--field", "--raw-field") and i + 1 < len(tokens):
            val = tokens[i + 1]
            if "=" in val:
                chunks.append(val.split("=", 1)[1])
            i += 2
            continue
        i += 1
    return "\n".join(chunks)


def scan(text):
    hits = []
    for pattern, label in SECRETS:
        m = re.search(pattern, text)
        if m:
            hits.append(("secret", label, m.group(0)[:12] + "..."))
    for pattern, label in ENV_LEAKS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            hits.append(("local environment", label, m.group(0)[:60]))
    return hits


def main():
    if os.environ.get("GH_HYGIENE", "").lower() == "off":
        return ALLOW
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return ALLOW
    if payload.get("tool_name") != "Bash":
        return ALLOW
    raw = (payload.get("tool_input") or {}).get("command") or ""
    if "gh" not in raw:
        return ALLOW

    heredocs, stripped = heredoc_bodies(raw)
    try:
        tokens = shlex.split(stripped, comments=False)
    except ValueError:
        tokens = stripped.split()
    if not is_publishing(tokens):
        return ALLOW

    hits = scan(collect_text(tokens, heredocs))
    if not hits:
        return ALLOW

    kind, label, sample = hits[0]
    extra = ""
    if len(hits) > 1:
        extra = "\nAlso found: " + ", ".join(f"{h[1]} ({h[2]})" for h in hits[1:4])
    sys.stderr.write(
        f"BLOCKED by gh-hygiene: this would publish {kind} detail to GitHub.\n"
        f"Found {label}: {sample!r}\n"
        f"{extra}\n\n"
        "GitHub text is public and permanent. Describe the change and its effect "
        "on the repository - not the environment you ran in. No local paths, no "
        "home directory, no tooling you happen to run inside, no \"on my machine\". "
        "If a local detail feels necessary, restate it as a property of the repo. "
        "Rewrite the body and try again.\n"
    )
    return DENY


if __name__ == "__main__":
    sys.exit(main())
