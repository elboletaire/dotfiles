#!/usr/bin/env python3
"""Regression suite for gh-hygiene.py. Run: python3 test-gh-hygiene.py"""
import json, os, shlex, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh-hygiene.py")
ALLOW, DENY = 0, 2

def run(cmd, env=None, tool="Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": cmd}})
    e = dict(os.environ); e.pop("GH_HYGIENE", None); e.update(env or {})
    p = subprocess.run([sys.executable, HOOK], input=payload, text=True,
                       capture_output=True, env=e)
    return p.returncode, p.stderr

LEAK = """Followed up on the rename question.

Claude Code stores an installed plugin at `~/.claude/plugins/cache/<mp>/<plugin>/<version>/`.
On my machine that is:

    ~/.claude/plugins/cache/vocdoni/vocdoni-integrator-sdk/0.1.0/skills/integrator-sdk/

On this machine the leftover is worse: `~/.claude/skills/integrator-sdk` is a symlink
into a vendored clone at `~/.claude/skills-vendor/integrator-sdk/skills/integrator-sdk`.
"""
CLEAN = ("Adds ranked-ballot decoding; adds tests for tie handling.\n\n"
         "Opus 5 here, controlled by elboletaire.\n\n"
         "The cache key includes the package version, so a rename without a version "
         "bump can leave installed users resolving the old name. Bumped to 0.2.0.")

CASES = []
def case(name, expect, cmd, env=None, tool="Bash"):
    CASES.append((name, expect, cmd, env, tool))

q = shlex.quote
case("real leak, inline --body", DENY, f"gh pr comment 51 --body {q(LEAK)}")
case("clean body (keeps 'elboletaire' signature)", ALLOW, f"gh pr comment 51 --body {q(CLEAN)}")
case("clean pr create", ALLOW, f"gh pr create --title {q('feat: ranked ballots')} --body {q(CLEAN)}")
case("leak via heredoc", DENY, "gh pr comment 51 --body-file - <<'EOF'\n" + LEAK + "\nEOF")
case("leak in --title", DENY, f"gh issue create --title {q('fails under /home/elboletaire/src')} --body {q(CLEAN)}")
case("gh pr review leak", DENY, f"gh pr review 51 --request-changes --body {q(LEAK)}")
case("gh api POST comment leak", DENY,
     f"gh api -X POST repos/o/r/issues/1/comments -f body={q(LEAK)}")
case("non-publishing gh is ignored", ALLOW, f"gh pr list --json number  # {LEAK[:80]}")
case("non-gh bash is ignored", ALLOW, f"grep -r '~/.claude/plugins' /home/elboletaire")
case("non-Bash tool ignored", ALLOW, f"gh pr comment 51 --body {q(LEAK)}", None, "Read")
case("secret: anthropic key", DENY,
     "gh pr comment 51 --body " + q("set sk-ant-api03-AAAAAAAAAAAAAAAAAAAA to run it"))
case("secret: github token", DENY,
     "gh issue comment 5 --body " + q("use ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 for CI"))
case("secret: private key", DENY,
     "gh pr comment 1 --body " + q("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n"))
case("aoe tooling mention", DENY,
     "gh pr comment 1 --body " + q("Reproduced after I ran aoe add . -w feat/x -l"))
case("tmux mention", DENY, "gh pr comment 1 --body " + q("Only reproduces inside tmux panes."))
case("escape hatch GH_HYGIENE=off", ALLOW,
     f"gh pr comment 51 --body {q(LEAK)}", {"GH_HYGIENE": "off"})

def main():
    # --body-file pointing at a real file on disk
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(LEAK); leak_path = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(CLEAN); clean_path = fh.name
    case("leak via --body-file on disk", DENY, f"gh pr comment 51 --body-file {leak_path}")
    case("clean --body-file (path itself is /tmp)", ALLOW, f"gh pr comment 51 --body-file {clean_path}")

    failed = 0
    for name, expect, cmd, env, tool in CASES:
        code, err = run(cmd, env, tool)
        ok = code == expect
        failed += not ok
        verdict = "PASS" if ok else "FAIL"
        want = "deny" if expect == DENY else "allow"
        got = "deny" if code == DENY else f"allow({code})"
        print(f"  [{verdict}] {name}: want {want}, got {got}")
        if not ok and err:
            print("         " + err.strip().splitlines()[0])
    os.unlink(leak_path); os.unlink(clean_path)
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
