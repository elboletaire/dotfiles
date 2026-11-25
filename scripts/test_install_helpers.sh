#!/bin/bash
# Regression tests for scripts/install.sh helpers.
# Uses a fake HOME, a mock apm and stubbed package managers; never touches the
# real home or system.
set -euo pipefail

# ── colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}PASS${NC} $*"; }
fail() { echo -e "  ${RED}FAIL${NC} $*"; exit 1; }
info() { echo -e "  ${CYAN}INFO${NC} $*"; }

TESTDIR="$(mktemp -d)"
export TESTDIR
trap 'rm -rf "$TESTDIR"' EXIT

FAKE_HOME="$TESTDIR/home"
mkdir -p "$FAKE_HOME/.apm"
export HOME="$FAKE_HOME"
unset OCTOPILOT_DIR

DOTFILES="$TESTDIR/dotfiles"
mkdir -p "$DOTFILES/ai"
mkdir -p "$DOTFILES/scripts"

# ── mock apm ──────────────────────────────────────────────────────────────
# Logs each call with its directory. install and update write the lock and
# manifest named by MOCK_APM_NEW_LOCK / MOCK_APM_NEW_MANIFEST, then fail when
# MOCK_APM_FAIL is set, which is the worst case for the caller.
MOCK_APM="$TESTDIR/bin/apm"
mkdir -p "$(dirname "$MOCK_APM")"
APM_VERSION_FILE="$TESTDIR/apm-version"
export APM_VERSION_FILE
echo 0.39.0 > "$APM_VERSION_FILE"
cat > "$MOCK_APM" <<'MOCK'
#!/bin/bash
echo "apm $* (in $PWD)" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  --version) echo "Agent Package Manager (APM) CLI version $(cat "$APM_VERSION_FILE") (mock)" ;;
  install|update)
    if [ -n "${MOCK_APM_NEW_LOCK:-}" ]; then printf '%s\n' "$MOCK_APM_NEW_LOCK" > "$HOME/.apm/apm.lock.yaml"; fi
    if [ -n "${MOCK_APM_NEW_MANIFEST:-}" ]; then printf '%s\n' "$MOCK_APM_NEW_MANIFEST" > "$HOME/.apm/apm.yml"; fi
    if [ -n "${MOCK_APM_FAIL:-}" ]; then echo "mock apm: $1 failed" >&2; exit 1; fi ;;
esac
exit 0
MOCK
chmod +x "$MOCK_APM"

OLD_PATH="$PATH"
export PATH="$(dirname "$MOCK_APM"):$TESTDIR/pkgstubs:$OLD_PATH"

# ── stubbed package managers ──────────────────────────────────────────────
# Installed names are listed in FAKE_BREW_FORMULAS / FAKE_PACMAN_PKGS. Every call
# is logged to pkg.log; nothing is ever installed or removed for real. These are
# binaries, not functions, so a test's own mock on PATH still wins.
PKG_STUBS="$TESTDIR/pkgstubs"
mkdir -p "$PKG_STUBS"
cat > "$PKG_STUBS/brew" <<'STUB'
#!/bin/bash
echo "brew $*" >> "$TESTDIR/pkg.log"
if [ "$1" = list ]; then
  case " $FAKE_BREW_FORMULAS " in *" $3 "*) exit 0 ;; esac
  exit 1
fi
exit 0
STUB
cat > "$PKG_STUBS/pacman" <<'STUB'
#!/bin/bash
echo "pacman $*" >> "$TESTDIR/pkg.log"
if [ "$1" = -Qq ]; then
  case " $FAKE_PACMAN_PKGS " in *" $2 "*) exit 0 ;; esac
  exit 1
fi
exit 0
STUB
printf '#!/bin/bash\nexec "$@"\n' > "$PKG_STUBS/sudo"
chmod +x "$PKG_STUBS"/*
export FAKE_BREW_FORMULAS="" FAKE_PACMAN_PKGS=""

# ── source install.sh functions ────────────────────────────────────────────
cp "$(cd "$(dirname "$0")/.." && pwd)/scripts/install.sh" "$DOTFILES/scripts/install.sh"

# Patch dotfiles dir for test env
sed "s|declare -r dotfiles=~/.dotfiles|declare -r dotfiles=$DOTFILES|" \
  "$DOTFILES/scripts/install.sh" > "$TESTDIR/install_patched.sh"

source "$TESTDIR/install_patched.sh"
REAL_OS=$OS
# Test 24b reassigns MODULES, so keep the sourced default for Test 27c.
DEFAULT_MODULE_ENTRY="${MODULES[0]}"

# Writes the tracked manifest and lock that install_skills and skills_bump read.
seed_ai() {
  mkdir -p "$DOTFILES/ai"
  printf '%s\n' "$1" > "$DOTFILES/ai/apm.yml"
  printf '%s\n' "$2" > "$DOTFILES/ai/apm.lock.yaml"
}

# Gives the fake home a clean global APM dir.
reset_global_apm() {
  rm -rf "$HOME/.apm"
  mkdir -p "$HOME/.apm"
}

echo ""
echo "=== Test 1: bash -n syntax check ==="
if bash -n "$DOTFILES/scripts/install.sh" 2>&1; then
  pass "install.sh passes bash -n"
else
  fail "install.sh has syntax errors"
fi


echo ""
echo "=== Test 2: install_apm leaves a current apm alone ==="
reset_global_apm
out=$(install_apm 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [[ "$out" == *"apm already installed (0.39.0)"* ]] && ! grep -q ' install\| update' "$HOME/.apm/mock.log"; then
  pass "install_apm keeps apm 0.39.0 without installing"
else
  fail "install_apm should keep apm 0.39.0: $out"
fi

echo ""
echo "=== Test 2b: install_apm upgrades an older apm through the official installer ==="
echo 0.33.0 > "$APM_VERSION_FILE"
OS=Linux
curl() {
  local out="" prev="" arg
  for arg in "$@"; do
    [ "$prev" = -o ] && out=$arg
    prev=$arg
  done
  printf 'echo 0.39.0 > "%s"\n' "$APM_VERSION_FILE" > "$out"
}
out=$(install_apm 2>&1) && rc=0 || rc=$?
unset -f curl
OS=$REAL_OS
if [ "$rc" -eq 0 ] && [[ "$out" == *"upgrading"* ]] && [ "$(_apm_version)" = 0.39.0 ]; then
  pass "install_apm reruns the installer for apm 0.33.0"
else
  fail "install_apm did not upgrade apm 0.33.0: rc=$rc $out"
fi
echo 0.39.0 > "$APM_VERSION_FILE"

echo ""
echo "=== Test 2c: install_apm fails when the installer cannot be downloaded ==="
echo 0.33.0 > "$APM_VERSION_FILE"
OS=Linux
curl() { return 1; }
out=$(install_apm 2>&1) && rc=0 || rc=$?
unset -f curl
OS=$REAL_OS
echo 0.39.0 > "$APM_VERSION_FILE"
if [ "$rc" -ne 0 ] && [[ "$out" == *"Failed to download APM installer"* ]]; then
  pass "install_apm returns nonzero on a failed download"
else
  fail "install_apm should fail on a failed download: rc=$rc $out"
fi

echo ""
echo "=== Test 3: install_skills copies in as regular files and runs a plain apm install ==="
reset_global_apm
seed_ai "manifest-v1" "lock-v1"
ln -s "$DOTFILES/ai/apm.yml" "$HOME/.apm/apm.yml"
out=$(install_skills 2>&1) || fail "install_skills failed: $out"
if [ ! -L "$HOME/.apm/apm.yml" ] && [ "$(cat "$HOME/.apm/apm.yml")" = manifest-v1 ] &&
   [ ! -L "$HOME/.apm/apm.lock.yaml" ] && [ "$(cat "$HOME/.apm/apm.lock.yaml")" = lock-v1 ]; then
  pass "global manifest and lock are regular copies (a symlink was replaced, not written through)"
else
  fail "global files were not regular copies of ai/"
fi
if grep -qxF "apm install -g --target agent-skills,claude (in $HOME/.apm)" "$HOME/.apm/mock.log"; then
  pass "apm install -g runs from ~/.apm with both targets"
else
  fail "apm install was not run from ~/.apm: $(cat "$HOME/.apm/mock.log")"
fi
if [ "$(cat "$DOTFILES/ai/apm.yml")" = manifest-v1 ] && [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = lock-v1 ] &&
   [[ "$out" != *"changed"* ]]; then
  pass "an unchanged lock is not copied back and ai/ is untouched"
else
  fail "install_skills changed ai/ without a lock change: $out"
fi

echo ""
echo "=== Test 3b: install_skills copies back a lock that APM rewrote ==="
export MOCK_APM_NEW_LOCK="lock-v2"
out=$(install_skills 2>&1) || fail "install_skills failed: $out"
unset MOCK_APM_NEW_LOCK
if [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = lock-v2 ] && [[ "$out" == *"ai/apm.lock.yaml changed"* ]] &&
   [ "$(cat "$DOTFILES/ai/apm.yml")" = manifest-v1 ]; then
  pass "changed lock is copied to ai/ with a note; manifest stays"
else
  fail "lock copy-back wrong: $out"
fi

echo ""
echo "=== Test 3c: a failing apm install returns nonzero and leaves ai/ untouched ==="
export MOCK_APM_NEW_LOCK="lock-v3" MOCK_APM_FAIL=1
out=$(install_skills 2>&1) && rc=0 || rc=$?
unset MOCK_APM_NEW_LOCK MOCK_APM_FAIL
if [ "$rc" -ne 0 ] && [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = lock-v2 ] &&
   [[ "$out" == *"ai/ unchanged"* ]]; then
  pass "install_skills fails and ai/apm.lock.yaml keeps lock-v2"
else
  fail "install_skills failure handling wrong (rc=$rc): $out"
fi

echo ""
echo "=== Test 4: skills_bump updates through apm and copies the new files back ==="
git -C "$DOTFILES" init -q
git -C "$DOTFILES" add ai scripts
git -C "$DOTFILES" -c user.name=test -c user.email=test@example.invalid commit -qm base
seed_ai "manifest-v1" "lock-v2"
reset_global_apm
export MOCK_APM_NEW_LOCK="lock-bumped" MOCK_APM_NEW_MANIFEST="manifest-bumped"
out=$(skills_bump 2>&1) || fail "skills_bump failed: $out"
unset MOCK_APM_NEW_LOCK MOCK_APM_NEW_MANIFEST
if grep -qxF "apm update -g --yes --target agent-skills,claude (in $HOME/.apm)" "$HOME/.apm/mock.log" &&
   [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = lock-bumped ] &&
   [ "$(cat "$DOTFILES/ai/apm.yml")" = manifest-bumped ] &&
   [[ "$out" == *"apm.lock.yaml"* ]]; then
  pass "skills_bump runs apm update -g --yes and copies both files back, showing the diff"
else
  fail "skills_bump wrong: $out"
fi

echo ""
echo "=== Test 4b: a failing skills_bump leaves ai/ untouched ==="
export MOCK_APM_NEW_LOCK="lock-broken" MOCK_APM_FAIL=1
out=$(skills_bump 2>&1) && rc=0 || rc=$?
unset MOCK_APM_NEW_LOCK MOCK_APM_FAIL
if [ "$rc" -ne 0 ] && [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = lock-bumped ] &&
   [ "$(cat "$DOTFILES/ai/apm.yml")" = manifest-bumped ] && [[ "$out" == *"ai/ unchanged"* ]]; then
  pass "skills_bump keeps the tracked files when apm update fails"
else
  fail "skills_bump failure should leave ai/ alone (rc=$rc): $out"
fi

echo ""
echo "=== Test 4e: a symlinked global lock is replaced by a regular copy ==="
PLAIN_LOCK="lockfile_version: '4'
dependencies: []"
seed_ai "manifest-v1" "$PLAIN_LOCK"
reset_global_apm
ln -s "$DOTFILES/ai/apm.lock.yaml" "$HOME/.apm/apm.lock.yaml"
out=$(install_skills 2>&1) || fail "install_skills failed: $out"
if [ ! -L "$HOME/.apm/apm.lock.yaml" ] && [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = "$PLAIN_LOCK" ]; then
  pass "~/.apm/apm.lock.yaml is never a symlink after copying"
else
  fail "global lock is still a symlink"
fi
seed_ai "manifest-v1" "$PLAIN_LOCK"

echo ""
echo "=== Test 4h: install_skills refuses an apm older than 0.39 ==="
echo 0.33.0 > "$APM_VERSION_FILE"
out=$(install_skills 2>&1) && rc=0 || rc=$?
echo 0.39.0 > "$APM_VERSION_FILE"
if [ "$rc" -ne 0 ] && [[ "$out" == *"install.sh ai"* ]]; then
  pass "install_skills tells the user to run install.sh ai"
else
  fail "install_skills accepted apm 0.33.0 (rc=$rc): $out"
fi

echo ""
echo "=== Test 4i: a failed migration install names the backup and the fix ==="
reset_global_apm
printf '%s\n' "dependencies:" "  apm:" "    - /Users/someone/.dotfiles/ai" > "$HOME/.apm/apm.yml"
mkdir -p "$HOME/.agents/skills/find-skills"
export MOCK_APM_FAIL=1
out=$(install_skills 2>&1) && rc=0 || rc=$?
unset MOCK_APM_FAIL
if [ "$rc" -ne 0 ] && [[ "$out" == *"legacy-skills-"* ]] && [[ "$out" == *"install.sh ai"* ]]; then
  pass "the error says where the moved skills are and what to run"
else
  fail "migration failure message unclear (rc=$rc): $out"
fi
seed_ai "manifest-v1" "$PLAIN_LOCK"

echo ""
echo "=== Test 4j: skills-bump retires the 0.33 package and cleans legacy skills first ==="
reset_global_apm
printf '%s\n' "dependencies:" "  apm:" "    - /Users/someone/.dotfiles/ai" > "$HOME/.apm/apm.yml"
mkdir -p "$HOME/.agents/skills/aoe"
out=$(skills_bump 2>&1) || fail "skills_bump failed: $out"
if [ ! -e "$HOME/.agents/skills/aoe" ] && [[ "$out" == *"Retiring the local"* ]] &&
   [ -d "$oldfiles/legacy-skills-$(date +%Y%m%d)/.agents/skills/aoe" ]; then
  pass "skills-bump moves the legacy and old-package skills aside before updating"
else
  fail "skills-bump did not retire first: $out"
fi
seed_ai "manifest-v1" "$PLAIN_LOCK"

echo ""
echo "=== Test 4c: update and ai paths install skills but never bump them ==="
reset_global_apm
: > "$TESTDIR/calls.log"
(
  install_nvm() { :; }
  install_ai_agents() { :; }
  install_herdr() { :; }
  install_herdr_app() { :; }
  install_uv() { :; }
  install_rtk() { :; }
  symlink_ai() { :; }
  merge_claude_settings() { :; }
  install_modules() { :; }
  link_herdr_config() { :; }
  link_herdr_plugin() { :; }
  link_herdr_app() { :; }
  install_skills() { echo install_skills >> "$TESTDIR/calls.log"; }
  git() { :; }
  symlink() { :; }
  symlink_config() { :; }
  do_update_ai >/dev/null 2>&1
  do_update >/dev/null 2>&1 || true
)
if grep -qx install_skills "$TESTDIR/calls.log" && ! grep -q 'update' "$HOME/.apm/mock.log" 2>/dev/null; then
  pass "do_update and do_update_ai call install_skills and never apm update"
else
  fail "update/ai path bumped skills or skipped install_skills: $(cat "$TESTDIR/calls.log")"
fi

echo ""
echo "=== Test 4d: a global manifest with a local package retires its skills once ==="
reset_global_apm
mkdir -p "$HOME/.agents/skills/brainstorming" "$HOME/.claude/skills/brainstorming" \
  "$HOME/.agents/skills/find-skills" "$HOME/.agents/skills/aoe" \
  "$HOME/.claude/hooks/contributing/hooks"
printf '%s\n' '[{"_apm_source": "vocdoni/skills/plugins/vocdoni-contributing"}]' > "$HOME/.claude/apm-hooks.json"
cat > "$HOME/.apm/apm.yml" <<'YML'
dependencies:
  apm:
    - /Users/someone/.dotfiles/ai
YML
cat > "$HOME/.apm/apm.lock.yaml" <<'LOCK'
lockfile_version: '4'
dependencies:
- repo_url: _local/ai
  deployed_files:
  - .claude/skills/brainstorming
  - .claude/skills/brainstorming/SKILL.md
LOCK
seed_ai "manifest-v1" "lockfile_version: '4'
dependencies:
- repo_url: vercel-labs/skills
  deployed_files:
  - .agents/skills/find-skills"
_retire_local_apm_package "$HOME/.apm" "$DOTFILES/ai/apm.lock.yaml" > "$TESTDIR/retire.log"
retired="$oldfiles/legacy-skills-$(date +%Y%m%d)"
if [ -d "$retired/.agents/skills/brainstorming" ] && [ -d "$retired/.claude/skills/brainstorming" ] &&
   [ -d "$retired/.agents/skills/find-skills" ] && [ ! -e "$HOME/.agents/skills/find-skills" ] &&
   [ -f "$retired/.claude/apm-hooks.json" ] && [ -d "$retired/.claude/hooks/contributing" ] &&
   [ ! -e "$HOME/.claude/apm-hooks.json" ] && [ -d "$HOME/.agents/skills/aoe" ]; then
  pass "skills of the old local package and of the new lock move aside; unrelated skills stay"
else
  fail "retirement moved the wrong things: $(cat "$TESTDIR/retire.log")"
fi
mkdir -p "$HOME/.agents/skills/find-skills"
printf 'dependencies:\n  apm:\n    - git: https://github.com/x/y.git\n' > "$HOME/.apm/apm.yml"
_retire_local_apm_package "$HOME/.apm" "$DOTFILES/ai/apm.lock.yaml" > "$TESTDIR/retire2.log"
if [ -d "$HOME/.agents/skills/find-skills" ] && [ ! -s "$TESTDIR/retire2.log" ]; then
  pass "a manifest without a local package retires nothing"
else
  fail "retirement ran without a local package: $(cat "$TESTDIR/retire2.log")"
fi

echo ""
echo "=== Test 5: cleanup_legacy removes unmanaged legacy skills, keeps APM-deployed ones ==="
rm -rf "$HOME/.agents" "$HOME/.claude/skills" "$HOME/.pi" "$HOME/old_dotfiles" "$HOME/elsewhere"
reset_global_apm
mkdir -p "$HOME/.agents/skills/aoe" "$HOME/.agents/skills/tsdown" "$HOME/.agents/skills/agent-browser" \
  "$HOME/.agents/skills/some-skill" \
  "$HOME/.agents/skills/brag" "$HOME/.claude/skills/brag" "$HOME/.claude/skills" "$HOME/.pi/agent/skills" \
  "$HOME/elsewhere/foreign-skill"
echo "name: aoe" > "$HOME/.agents/skills/aoe/SKILL.md"
echo "name: brag" > "$HOME/.agents/skills/brag/SKILL.md"
echo "stale" > "$HOME/.agents/.skill-lock.json"
cat > "$HOME/.apm/apm.lock.yaml" <<'LOCK'
lockfile_version: '4'
dependencies:
- repo_url: owner/brag-pack
  deployed_files:
  - .agents/skills/brag
  - .claude/skills/brag
LOCK
ln -s ../../.agents/skills/aoe "$HOME/.claude/skills/aoe"
ln -s "$HOME/.agents/skills/some-skill" "$HOME/.pi/agent/skills/some-skill"
ln -s "$HOME/elsewhere/foreign-skill" "$HOME/.pi/agent/skills/foreign"
ln -s "$HOME/nowhere" "$HOME/.claude/skills/vocdoni-sdk"
ln -s "$HOME/nowhere" "$HOME/.pi/agent/skills/dangling-thing"
cleanup_legacy > "$TESTDIR/cleanup5.log" 2>&1
backup_skills="$oldfiles/legacy-skills-$(date +%Y%m%d)"
if [ -d "$backup_skills/.agents/skills/aoe" ] && [ -d "$backup_skills/.agents/skills/tsdown" ] &&
   [ -d "$backup_skills/.agents/skills/agent-browser" ] && [ -f "$backup_skills/.agents/.skill-lock.json" ] &&
   [ ! -e "$HOME/.agents/skills/aoe" ] && [ ! -e "$HOME/.agents/skills/agent-browser" ]; then
  pass "unmanaged legacy dirs are moved to the legacy backup, not deleted"
else
  fail "unmanaged legacy dirs not moved: $(cat "$TESTDIR/cleanup5.log")"
fi
if [ -d "$HOME/.agents/skills/brag" ] && [ -d "$HOME/.claude/skills/brag" ]; then
  pass "APM-deployed brag is kept in both skill dirs"
else
  fail "cleanup_legacy removed APM-deployed brag"
fi
if [ ! -L "$HOME/.claude/skills/aoe" ] && [ ! -L "$HOME/.pi/agent/skills/some-skill" ] &&
   [ ! -L "$HOME/.claude/skills/vocdoni-sdk" ] && [ ! -L "$HOME/.pi/agent/skills/dangling-thing" ] &&
   [ -L "$HOME/.pi/agent/skills/foreign" ]; then
  pass "legacy links, Pi links into ~/.agents/skills and dangling links removed; foreign Pi link kept"
else
  fail "link cleanup wrong: $(cat "$TESTDIR/cleanup5.log")"
fi

echo ""
echo "=== Test 5b: cleanup_legacy uninstalls packages, removes binaries and moves state ==="
rm -rf "$HOME/.local/bin" "$HOME/bin" "$HOME/.cargo/bin" "$HOME/.local/state/aoe" "$HOME/Library/Application Support/agent-deck" "$HOME/old_dotfiles"
mkdir -p "$HOME/.local/bin" "$HOME/bin" "$HOME/.cargo/bin" "$HOME/.local/state/aoe" "$HOME/Library/Application Support/agent-deck"
touch "$HOME/bin/aoe" "$HOME/.cargo/bin/agent-deck"
: > "$TESTDIR/pkg.log"
(
  OS=Darwin
  export FAKE_BREW_FORMULAS="aoe"
  cleanup_legacy > "$TESTDIR/cleanup5b.log" 2>&1
)
if grep -qxF "brew uninstall --formula aoe" "$TESTDIR/pkg.log" && ! grep -q 'uninstall --formula agent-deck' "$TESTDIR/pkg.log" &&
   [ ! -e "$HOME/bin/aoe" ] && [ ! -e "$HOME/.cargo/bin/agent-deck" ] &&
   [ ! -e "$HOME/.local/state/aoe" ] && [ ! -e "$HOME/Library/Application Support/agent-deck" ] &&
   [ -d "$oldfiles/legacy-session-managers-$(date +%Y%m%d)/Library/Application Support/agent-deck" ]; then
  pass "brew formula aoe is uninstalled, only when installed; binaries and state removed"
else
  fail "package/binary/state cleanup wrong: $(cat "$TESTDIR/pkg.log") $(cat "$TESTDIR/cleanup5b.log")"
fi
: > "$TESTDIR/pkg.log"
(
  OS=Linux
  export FAKE_PACMAN_PKGS="agent-deck aoe"
  cleanup_legacy > /dev/null 2>&1
)
if grep -qxF "pacman -Rns --noconfirm aoe agent-deck" "$TESTDIR/pkg.log"; then
  pass "pacman removes installed aoe and agent-deck packages in one call"
else
  fail "pacman cleanup wrong: $(cat "$TESTDIR/pkg.log")"
fi

echo ""
echo "=== Test 9: merge_claude_settings removes agent-deck, aoe and old contributing hooks ==="
mkdir -p "$DOTFILES/ai/claude" "$HOME/.claude"
cat > "$DOTFILES/ai/claude/settings.json" <<'JSON'
{"env": {"CLAUDE_CODE_PLUGIN_DIRS": "~/mods/a"}}
JSON
python3 - "$HOME/.claude/settings.json" <<'PY'
import json, os, sys
home = os.environ["HOME"]
hooks = {
    "SessionStart": [
        {"hooks": [{"type": "command", "command": "agent-deck hook-handler", "async": True}]},
        {"hooks": [{"type": "command", "command": "sh -c '[ -n \"$AOE_INSTANCE_ID\" ] || exit 0' # aoe-hooks"}]},
    ],
    "PreToolUse": [
        {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "rtk hook claude"},
            {"type": "command", "command": "agent-deck hook-handler"},
        ]},
    ],
    "Stop": [
        {"hooks": [{"type": "command", "command": 'bash "$HOME/.claude/hooks/contributing/hooks/session-start.sh"'}]},
    ],
    "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": f'bash "{home}/.claude/hooks/contributing/hooks/session-start.sh"'}]},
    ],
    "Notification": [
        {"hooks": [{"type": "command", "command": "/usr/local/bin/notify"}]},
    ],
    "PostToolUse": [
        {"hooks": [{"type": "command", "command": "bash '/home/other/.claude/hooks/contributing/hooks/session-start.sh'"}]},
    ],
}
json.dump({"hooks": hooks, "theme": "dark"}, open(sys.argv[1], "w"))
PY
merge_claude_settings > /dev/null 2>&1
python3 - "$HOME/.claude/settings.json" <<'PY' && pass "legacy hooks removed, rtk and other hooks and unrelated keys kept, empty events dropped" || fail "merge_claude_settings left legacy hooks: $(cat "$HOME/.claude/settings.json")"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["theme"] == "dark", d
assert d["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == "~/mods/a", d
assert d["hooks"] == {
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": "/usr/local/bin/notify"}]}],
}, d["hooks"]
PY
echo ""
echo "=== Test 24: link_herdr_plugin links, keeps and relinks the herdr plugins ==="
MOCK_HERDR="$TESTDIR/bin/herdr"
HERDR_STATE="$TESTDIR/herdr-linked"
cat > "$MOCK_HERDR" <<MOCK
#!/bin/bash
echo "herdr \$*" >> "$TESTDIR/herdr.log"
case "\$1 \$2" in
  "plugin list")
    if [ -s "$HERDR_STATE" ]; then
      printf '{"result":{"plugins":[{"plugin_id":"elboletaire.arxiu","plugin_root":"%s"}]}}' "\$(cat "$HERDR_STATE")"
    else
      printf '{"result":{"plugins":[]}}'
    fi ;;
  "plugin link") echo "\$3" > "$HERDR_STATE" ;;
  "plugin unlink") : > "$HERDR_STATE" ;;
  "status server")
    if [ -e "$TESTDIR/herdr-down" ]; then echo "Status: not running"; else echo "Status: running"; fi ;;
esac
MOCK
chmod +x "$MOCK_HERDR"
want="$DOTFILES/ai/arxiu/herdr"

touch "$TESTDIR/herdr-down"
: > "$TESTDIR/herdr.log"
link_herdr_plugin >/dev/null
if grep -q "plugin " "$TESTDIR/herdr.log"; then
  fail "ran plugin commands although no herdr server is running"
else
  pass "skips the plugin link when no herdr server is running"
fi
rm -f "$TESTDIR/herdr-down"

: > "$TESTDIR/herdr.log"
link_herdr_plugin >/dev/null
if grep -q "^herdr plugin link $DOTFILES/ai/arxiu/herdr$" "$TESTDIR/herdr.log" &&
   grep -q "^herdr plugin link $DOTFILES/ai/taller/herdr$" "$TESTDIR/herdr.log" &&
   ! grep -q "plugin link.*octopilot" "$TESTDIR/herdr.log"; then
  pass "links the arxiu and taller plugins, not octopilot's"
else
  fail "wrong herdr plugin links: $(grep 'plugin link' "$TESTDIR/herdr.log" | tr '\n' ';')"
fi

: > "$HERDR_STATE"
: > "$TESTDIR/herdr.log"
_link_herdr_plugin elboletaire.arxiu "$want" >/dev/null
[ "$(cat "$HERDR_STATE")" = "$want" ] && pass "links the plugin when absent" \
  || fail "plugin not linked to $want"

: > "$TESTDIR/herdr.log"
_link_herdr_plugin elboletaire.arxiu "$want" >/dev/null
if grep -q "plugin link\|plugin unlink" "$TESTDIR/herdr.log"; then
  fail "re-ran link/unlink although already linked to the right root"
else
  pass "leaves an already-correct link alone"
fi

echo "/somewhere/.worktrees/feat-herdr/ai/arxiu/herdr" > "$HERDR_STATE"
: > "$TESTDIR/herdr.log"
_link_herdr_plugin elboletaire.arxiu "$want" >/dev/null
if grep -q "plugin unlink elboletaire.arxiu" "$TESTDIR/herdr.log" &&
   [ "$(cat "$HERDR_STATE")" = "$want" ]; then
  pass "relinks a plugin that points at another checkout"
else
  fail "did not relink from a stale root"
fi

rm -f "$MOCK_HERDR"

echo ""
echo "=== Test 24b: install_module clones, fast-forwards and runs a module's install.sh ==="
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.invalid
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.invalid
MOD="$TESTDIR/module"
MOD_REMOTE="$MOD/remote.git"
MOD_WORK="$MOD/work"
MOD_DIR="$MOD/checkout"
MOD_RUNS="$MOD/runs.log"
rm -rf "$MOD"
mkdir -p "$MOD_WORK"
git init -q --bare -b main "$MOD_REMOTE"
git init -q -b main "$MOD_WORK"
printf '#!/bin/bash\necho ran >> "%s"\n' "$MOD_RUNS" > "$MOD_WORK/install.sh"
chmod +x "$MOD_WORK/install.sh"
# Commits a new version and pushes it to the bare remote.
publish() {
  echo "$1" > "$MOD_WORK/version"
  git -C "$MOD_WORK" add -A
  git -C "$MOD_WORK" commit -q -m "$1"
  git -C "$MOD_WORK" push -q "$MOD_REMOTE" main
}
runs() { wc -l < "$MOD_RUNS" 2>/dev/null | tr -d ' ' || true; }
publish v1
MODULES=("octopilot|$MOD_REMOTE|$MOD_DIR")

out=$(install_modules 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [ -d "$MOD_DIR/.git" ] && [ "$(runs)" = 1 ] && [[ "$out" == *"Cloning octopilot"* ]]; then
  pass "clones a missing module and runs its install.sh"
else
  fail "fresh clone: rc=$rc $out"
fi

publish v2
: > "$MOD_RUNS"
out=$(install_modules update 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [ "$(git -C "$MOD_DIR" log -1 --format=%s)" = v2 ] && [ "$(runs)" = 1 ]; then
  pass "update fast-forwards a clean checkout and runs its install.sh"
else
  fail "update did not fast-forward: rc=$rc $out"
fi

publish v3
echo local >> "$MOD_DIR/version"
out=$(install_modules update 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [[ "$out" == *"uncommitted changes"* ]] && [ "$(git -C "$MOD_DIR" log -1 --format=%s)" = v2 ] && grep -q local "$MOD_DIR/version"; then
  pass "update leaves a dirty checkout alone"
else
  fail "dirty checkout was touched: rc=$rc $out"
fi
git -C "$MOD_DIR" checkout -q -- version

git -C "$MOD_DIR" checkout -q -b topic
out=$(install_modules update 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [[ "$out" == *"not on its default branch"* ]] && [ "$(git -C "$MOD_DIR" symbolic-ref --short HEAD)" = topic ]; then
  pass "update leaves a checkout on another branch alone"
else
  fail "other-branch checkout was touched: rc=$rc $out"
fi
git -C "$MOD_DIR" checkout -q main

git -C "$MOD_DIR" remote set-url origin "$MOD/gone.git"
out=$(install_modules update 2>&1) && rc=0 || rc=$?
git -C "$MOD_DIR" remote set-url origin "$MOD_REMOTE"
if [ "$rc" -eq 0 ] && [[ "$out" == *"could not fast-forward"* ]] && [ "$(git -C "$MOD_DIR" log -1 --format=%s)" = v2 ]; then
  pass "update keeps the checkout when the remote is unreachable"
else
  fail "unreachable remote was not tolerated: rc=$rc $out"
fi

git -C "$MOD_DIR" remote set-head origin -d >/dev/null
out=$(install_modules update 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [ "$(git -C "$MOD_DIR" log -1 --format=%s)" = v3 ]; then
  pass "update finds the default branch without origin/HEAD and fast-forwards"
else
  fail "update skipped a checkout without origin/HEAD: rc=$rc $out"
fi

publish v4
git -C "$MOD_DIR" remote set-head origin -d >/dev/null
git -C "$MOD_DIR" remote set-url origin "$MOD/gone.git"
out=$(install_modules update 2>&1) && rc=0 || rc=$?
git -C "$MOD_DIR" remote set-url origin "$MOD_REMOTE"
if [ "$rc" -eq 0 ] && [[ "$out" == *"could not fast-forward"* ]] && [[ "$out" != *"default branch"* ]]; then
  pass "without origin/HEAD and offline, falls back to the upstream and keeps the checkout"
else
  fail "upstream fallback did not pick main: rc=$rc $out"
fi

NOGIT_DIR="$MOD/nogit"
mkdir -p "$NOGIT_DIR"
out=$(install_module nogit "$MOD_REMOTE" "$NOGIT_DIR" update 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [[ "$out" == *"not a git checkout"* ]]; then
  pass "warns about a module dir that is not a git checkout and does not touch it"
else
  fail "non-git dir not flagged: rc=$rc $out"
fi

NOEXEC_DIR="$MOD/noexec"
git init -q "$NOEXEC_DIR"
printf '#!/bin/bash\necho ran\n' > "$NOEXEC_DIR/install.sh"
out=$(install_module noexec "$MOD_REMOTE" "$NOEXEC_DIR" 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [[ "$out" == *"not executable"* ]]; then
  pass "warns about a module install.sh that is not executable, and skips it"
else
  fail "non-executable install.sh not flagged: rc=$rc $out"
fi

FAIL_DIR="$MOD/failing"
mkdir -p "$FAIL_DIR"
printf '#!/bin/bash\nexit 3\n' > "$FAIL_DIR/install.sh"
chmod +x "$FAIL_DIR/install.sh"
out=$(install_module failing "$MOD_REMOTE" "$FAIL_DIR" 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [[ "$out" == *"install.sh failed"* ]]; then
  pass "a failing module install.sh warns and returns 0"
else
  fail "failing install.sh aborted: rc=$rc $out"
fi

PLAIN_DIR="$MOD/plain"
git init -q "$PLAIN_DIR"
out=$(install_module plain "$MOD_REMOTE" "$PLAIN_DIR" 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [ -z "$out" ]; then
  pass "a module without install.sh is skipped quietly"
else
  fail "missing install.sh was not quiet: rc=$rc $out"
fi

out=$(install_module gone "$MOD/nope.git" "$MOD/gone" 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [[ "$out" == *"could not clone"* ]] && [ ! -e "$MOD/gone" ]; then
  pass "a failed clone warns and returns 0"
else
  fail "failed clone aborted: rc=$rc $out"
fi

out=$(install_module new "$MOD_REMOTE" "$MOD/never" relink 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && [ ! -e "$MOD/never" ]; then
  pass "relink mode never clones a missing module"
else
  fail "relink cloned a module: rc=$rc $out"
fi
unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL
rm -rf "$MOD"

echo ""
echo "=== Test 25: install_herdr installs, upgrades and wires only missing integrations ==="
MOCK_BIN="$TESTDIR/bin"
for tool in herdr yay brew claude pi; do
  cat > "$MOCK_BIN/$tool" <<MOCK
#!/bin/bash
echo "$tool \$*" >> "$TESTDIR/tools.log"
if [ "$tool \$1 \$2" = "herdr integration status" ]; then
  printf 'pi: not installed (x)\nclaude: current (v10) (y)\ncodex: current (v8) (z)\n'
fi
MOCK
  chmod +x "$MOCK_BIN/$tool"
done
# pacman owns herdr only when PACMAN_OWNS is set.
cat > "$MOCK_BIN/pacman" <<MOCK
#!/bin/bash
echo "pacman \$*" >> "$TESTDIR/tools.log"
[ -n "\${PACMAN_OWNS:-}" ]
MOCK
chmod +x "$MOCK_BIN/pacman"
# brew owns herdr when PATH's herdr is the link under its prefix.
BREW_PREFIX="$TESTDIR/brew"
mkdir -p "$BREW_PREFIX/bin"
ln -sf "$MOCK_BIN/herdr" "$BREW_PREFIX/bin/herdr"
cat > "$MOCK_BIN/brew" <<MOCK
#!/bin/bash
echo "brew \$*" >> "$TESTDIR/tools.log"
if [ "\$1" = --prefix ]; then echo "$BREW_PREFIX"; fi
MOCK
chmod +x "$MOCK_BIN/brew"
# The package stubs above may already have been looked up: forget the cached paths.
hash -r
OS_SAVED="${OS:-}"
OS=Linux

: > "$TESTDIR/tools.log"
install_herdr >/dev/null
if grep -q "^yay" "$TESTDIR/tools.log"; then
  fail "install_herdr ran yay although herdr is already installed"
else
  pass "skips the package install when herdr is present"
fi
if grep -q "^herdr integration install pi$" "$TESTDIR/tools.log" &&
   ! grep -q "^herdr integration install claude" "$TESTDIR/tools.log"; then
  pass "installs only the integrations that are not current"
else
  fail "wrong integration installs: $(grep 'integration install' "$TESTDIR/tools.log" | tr '\n' ';')"
fi

: > "$TESTDIR/tools.log"
PACMAN_OWNS=1 install_herdr update >/dev/null
grep -q "^yay -S --needed --noconfirm herdr-bin$" "$TESTDIR/tools.log" \
  && pass "update upgrades a pacman-owned herdr through yay" \
  || fail "update did not run yay for a pacman-owned herdr"

OS=Darwin
: > "$TESTDIR/tools.log"
install_herdr update >/dev/null
grep -q "^brew upgrade herdr$" "$TESTDIR/tools.log" \
  && pass "update upgrades herdr through brew on macOS" \
  || fail "macOS update did not run brew upgrade herdr"
OS="$OS_SAVED"
for tool in herdr yay brew claude pi pacman; do rm -f "$MOCK_BIN/$tool"; done
rm -rf "$BREW_PREFIX"

echo ""
echo "=== Test 26: set_login_shell only runs chsh when the login shell is not zsh ==="
ZSH_PATH=$(command -v zsh || echo /usr/bin/zsh)
command() { [ "$1 $2" = "-v zsh" ] && echo "$ZSH_PATH" || builtin command "$@"; }
chsh() { echo "chsh $*" >> "$TESTDIR/tools.log"; }
OS_SAVED="${OS:-}"
OS=Linux

getent() { echo "me:x:1000:1000::/home/me:$ZSH_PATH"; }
: > "$TESTDIR/tools.log"
set_login_shell
[ -s "$TESTDIR/tools.log" ] \
  && fail "ran chsh although the login shell is already zsh" \
  || pass "skips chsh when the login shell is already zsh"

getent() { echo "me:x:1000:1000::/home/me:/bin/zsh"; }
: > "$TESTDIR/tools.log"
set_login_shell
[ -s "$TESTDIR/tools.log" ] \
  && fail "ran chsh for /bin/zsh, the same shell under another path" \
  || pass "treats zsh under another path as already set"

getent() { echo "me:x:1000:1000::/home/me:/bin/bash"; }
: > "$TESTDIR/tools.log"
set_login_shell
grep -q "^chsh -s $ZSH_PATH$" "$TESTDIR/tools.log" \
  && pass "runs chsh when the login shell is not zsh" \
  || fail "did not run chsh for a bash login shell"

OS=Darwin
dscl() { echo "UserShell: $ZSH_PATH"; }
: > "$TESTDIR/tools.log"
set_login_shell
[ -s "$TESTDIR/tools.log" ] \
  && fail "ran chsh on macOS although the login shell is already zsh" \
  || pass "reads the login shell through dscl on macOS"
OS="$OS_SAVED"
unset -f command getent dscl

echo ""
echo "=== Test: link_ai skips ~/old_dotfiles when no_backup is set ==="
mkdir -p "$DOTFILES/ai/prompts" "$HOME/.nobackup/commands"
echo stale > "$HOME/.nobackup/commands/old.md"
rm -rf "$oldfiles"
no_backup=1
link_ai "$DOTFILES/ai/prompts" "$HOME/.nobackup/commands"
no_backup=0
[ "$(readlink "$HOME/.nobackup/commands")" = "$DOTFILES/ai/prompts" ] \
  && pass "replaces the existing directory with the symlink" \
  || fail "did not link $HOME/.nobackup/commands"
[ ! -e "$oldfiles" ] \
  && pass "leaves no ~/old_dotfiles behind" \
  || fail "created $oldfiles despite no_backup"

mkdir -p "$HOME/.backup/commands"
link_ai "$DOTFILES/ai/prompts" "$HOME/.backup/commands"
[ -d "$oldfiles/commands" ] \
  && pass "still backs up to ~/old_dotfiles by default" \
  || fail "default link_ai no longer backs up"
rm -rf "$oldfiles"

echo ""
echo "=== Test 27: merge_claude_settings merges our keys and keeps the rest ==="
mkdir -p "$DOTFILES/ai/claude"
cat > "$DOTFILES/ai/claude/settings.json" <<'JSON'
{"env": {"CLAUDE_CODE_PLUGIN_DIRS": "~/mods/a:~/mods/b"}}
JSON
SETTINGS="$HOME/.claude/settings.json"
rm -rf "$HOME/.claude"

merge_claude_settings >/dev/null
if [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["env"]["CLAUDE_CODE_PLUGIN_DIRS"])' "$SETTINGS")" = "~/mods/a:~/mods/b" ] &&
   [ "$(stat -c %a "$SETTINGS" 2>/dev/null || stat -f %Lp "$SETTINGS")" = "600" ]; then
  pass "creates the settings file (mode 600) when there is none"
else
  fail "did not create the settings file from the base"
fi

cat > "$SETTINGS" <<'JSON'
{"env": {"OTHER": "1", "CLAUDE_CODE_PLUGIN_DIRS": "~/old"}, "hooks": {"Stop": [{"hooks": [{"command": "rtk x"}]}]}, "model": "opus"}
JSON
chmod 640 "$SETTINGS"
merge_claude_settings >/dev/null
if python3 - "$SETTINGS" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["env"] == {"OTHER": "1", "CLAUDE_CODE_PLUGIN_DIRS": "~/mods/a:~/mods/b"}, d["env"]
assert d["hooks"]["Stop"][0]["hooks"][0]["command"] == "rtk x"
assert d["model"] == "opus"
PY
then
  pass "merges into env and keeps tool-written keys"
else
  fail "lost or mangled keys while merging"
fi
[ -f "$SETTINGS.dotfiles-bak" ] && grep -q '"~/old"' "$SETTINGS.dotfiles-bak" \
  && pass "keeps a backup of the previous settings" || fail "no backup of the previous settings"
[ "$(stat -c %a "$SETTINGS" 2>/dev/null || stat -f %Lp "$SETTINGS")" = "640" ] \
  && pass "preserves the file's permissions" || fail "changed the file's permissions"

before=$(cat "$SETTINGS.dotfiles-bak")
out=$(merge_claude_settings)
if [ -z "$out" ] && [ "$(cat "$SETTINGS.dotfiles-bak")" = "$before" ]; then
  pass "rewrites nothing when already merged"
else
  fail "rewrote an already-merged settings file"
fi

echo '{ not json' > "$SETTINGS"
merge_claude_settings >/dev/null 2>&1
[ "$(cat "$SETTINGS")" = "{ not json" ] && pass "leaves an invalid settings file untouched" \
  || fail "overwrote an invalid settings file"
rm -rf "$HOME/.claude" "$DOTFILES/ai/claude/settings.json"

echo ""
echo "=== Test 27b: merge_claude_settings removes the retired vocdoni marketplace and plugin ==="
mkdir -p "$DOTFILES/ai/claude" "$HOME/.claude"
cat > "$DOTFILES/ai/claude/settings.json" <<'JSON'
{"env": {"CLAUDE_CODE_PLUGIN_DIRS": "~/mods/a"}}
JSON
cat > "$SETTINGS" <<'JSON'
{"enabledPlugins": {"vocdoni-contributing@vocdoni": true, "other@market": true}, "extraKnownMarketplaces": {"vocdoni": {"source": {"source": "github", "repo": "vocdoni/skills"}}}}
JSON
merge_claude_settings >/dev/null
if python3 - "$SETTINGS" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["enabledPlugins"] == {"other@market": True}, d["enabledPlugins"]
assert "extraKnownMarketplaces" not in d, d
assert d["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == "~/mods/a"
PY
then
  pass "removes the retired vocdoni keys and keeps other plugins"
else
  fail "retired vocdoni keys were not removed cleanly"
fi

printf '%s\n' '{"enabledPlugins": {"vocdoni-contributing@vocdoni": true}}' > "$SETTINGS"
merge_claude_settings >/dev/null
python3 -c 'import json,sys; assert "enabledPlugins" not in json.load(open(sys.argv[1]))' "$SETTINGS" \
  && pass "drops a parent object left empty by the retirement" \
  || fail "left an empty enabledPlugins object behind"
rm -rf "$HOME/.claude" "$DOTFILES/ai/claude/settings.json"

echo ""
echo "=== Test 27d: OCTOPILOT_DIR elsewhere rewrites the Octopilot plugin entry only ==="
cat > "$DOTFILES/ai/claude/settings.json" <<'JSON'
{"env": {"CLAUDE_CODE_PLUGIN_DIRS": "~/src/octopilot/plugin:~/x/y"}}
JSON
rm -rf "$HOME/.claude"
merge_claude_settings >/dev/null
got=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["env"]["CLAUDE_CODE_PLUGIN_DIRS"])' "$HOME/.claude/settings.json")
if [ "$got" = "~/src/octopilot/plugin:~/x/y" ] &&
   [ "$DEFAULT_MODULE_ENTRY" = "octopilot|git@github.com:elboletaire/octopilot.git|$FAKE_HOME/src/octopilot" ]; then
  pass "the default dir keeps ~/src/octopilot/plugin and the default MODULES entry"
else
  fail "default OCTOPILOT_DIR changed the settings: $got $DEFAULT_MODULE_ENTRY"
fi

octopilot_dir="$FAKE_HOME/work/octopilot"
rm -rf "$HOME/.claude"
merge_claude_settings >/dev/null
got=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["env"]["CLAUDE_CODE_PLUGIN_DIRS"])' "$HOME/.claude/settings.json")
if [ "$got" = "~/work/octopilot/plugin:~/x/y" ]; then
  pass "a dir under HOME is written with ~ and only its entry changes"
else
  fail "home-relative OCTOPILOT_DIR not written: $got"
fi

octopilot_dir="/opt/octopilot"
rm -rf "$HOME/.claude"
merge_claude_settings >/dev/null
got=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["env"]["CLAUDE_CODE_PLUGIN_DIRS"])' "$HOME/.claude/settings.json")
if [ "$got" = "/opt/octopilot/plugin:~/x/y" ]; then
  pass "a dir outside HOME is written as an absolute path"
else
  fail "absolute OCTOPILOT_DIR not written: $got"
fi
octopilot_dir="$HOME/src/octopilot"
rm -rf "$HOME/.claude" "$DOTFILES/ai/claude/settings.json"

echo ""
echo "=== Test 28: link_herdr_config links the tracked herdr config ==="
# Shadow the real herdr: a function wins over the PATH lookup, so nothing
# below ever reaches the installed binary.
# Test 15 stubs link_herdr_config out; take the real one from install.sh.
eval "$(sed -n '/^link_herdr_config() {/,/^}/p' "$TESTDIR/install_patched.sh")"
HERDR_CALLS="$TESTDIR/herdr-config.log"
HERDR_RUNNING=1
herdr() {
  echo "herdr $*" >> "$HERDR_CALLS"
  if [ "$1 $2" = "status server" ]; then
    if [ "$HERDR_RUNNING" = 1 ]; then echo "Status: running"; else echo "Status: not running"; fi
  fi
  return 0
}
HERDR_SRC="$DOTFILES/config/herdr/config.toml"
HERDR_DEST="$FAKE_HOME/.config/herdr/config.toml"
mkdir -p "$DOTFILES/config/herdr"
echo 'onboarding = false' > "$HERDR_SRC"
rm -rf "$FAKE_HOME/.config" "$FAKE_HOME/old_dotfiles"
: > "$HERDR_CALLS"

link_herdr_config >/dev/null
if [ -L "$HERDR_DEST" ] && [ "$(readlink "$HERDR_DEST")" = "$HERDR_SRC" ]; then
  pass "links the tracked config into a fresh ~/.config/herdr"
else
  fail "fresh link not created"
fi
grep -q "^herdr server reload-config$" "$HERDR_CALLS" \
  && pass "reloads a running herdr server after linking" \
  || fail "did not reload the running herdr server"

echo ""
echo "=== Test 29: link_herdr_config re-run is a no-op ==="
: > "$HERDR_CALLS"
out=$(link_herdr_config)
if [ -z "$out" ] && [ ! -s "$HERDR_CALLS" ] && [ "$(readlink "$HERDR_DEST")" = "$HERDR_SRC" ]; then
  pass "leaves the existing link alone and does not reload"
else
  fail "re-run printed or changed something: '$out'"
fi

echo ""
echo "=== Test 30: link_herdr_config backs up a regular file with other content ==="
rm -f "$HERDR_DEST"
echo 'onboarding = false  # replaced by an upgrade' > "$HERDR_DEST"
rm -rf "$FAKE_HOME/old_dotfiles"
out=$(link_herdr_config 2>&1)
backup=$(ls "$FAKE_HOME"/old_dotfiles/config/herdr-config.toml.* 2>/dev/null | head -n 1 || true)
if [ -L "$HERDR_DEST" ] && [ -n "$backup" ] && grep -q "replaced by an upgrade" "$backup"; then
  pass "moves the old file to old_dotfiles/config and links the tracked one"
else
  fail "old file not backed up under old_dotfiles/config"
fi
case "$out" in
  *WARNING*"$backup"*) pass "warns where the backup went" ;;
  *) fail "no warning naming the backup: $out" ;;
esac

echo ""
echo "=== Test 31: link_herdr_config replaces an identical regular file without a backup ==="
rm -f "$HERDR_DEST"
cp "$HERDR_SRC" "$HERDR_DEST"
rm -rf "$FAKE_HOME/old_dotfiles"
link_herdr_config >/dev/null
if [ -L "$HERDR_DEST" ] && [ ! -e "$FAKE_HOME/old_dotfiles" ]; then
  pass "replaces an identical file silently"
else
  fail "identical file was backed up or not replaced"
fi

echo ""
echo "=== Test 32: link_herdr_config does not reload when no herdr server is running ==="
rm -f "$HERDR_DEST"
cp "$HERDR_SRC" "$HERDR_DEST"
HERDR_RUNNING=0
: > "$HERDR_CALLS"
link_herdr_config >/dev/null
if [ -L "$HERDR_DEST" ] && ! grep -q "reload-config" "$HERDR_CALLS"; then
  pass "links but skips the reload when the server is down"
else
  fail "reloaded or failed to link with the server down"
fi

echo ""
echo "=== Test 33: link_herdr_config is skipped without herdr on PATH ==="
rm -f "$HERDR_DEST"
# A bin dir with only the tools link_herdr_config calls: herdr may sit in /usr/bin.
NOHERDR_BIN="$TESTDIR/noherdr-bin"
mkdir -p "$NOHERDR_BIN"
for tool in mkdir dirname readlink cmp rm mv date ln; do
  ln -sf "$(command -v $tool)" "$NOHERDR_BIN/$tool"
done
if ( unset -f herdr; PATH="$NOHERDR_BIN"; ! command -v herdr >/dev/null && link_herdr_config >/dev/null 2>&1 ) \
   && [ -L "$HERDR_DEST" ]; then
  pass "links the config and never fails without herdr"
else
  fail "link_herdr_config failed without herdr on PATH"
fi
unset -f herdr

echo ""
echo "=== Test 34: link_herdr_config leaves a whole-dir link into the dotfiles alone ==="
mkdir -p "$DOTFILES/config/herdr"
echo 'onboarding = false' > "$HERDR_SRC"
rm -rf "$FAKE_HOME/.config"
mkdir -p "$FAKE_HOME/.config"
ln -s "$DOTFILES/config/herdr" "$FAKE_HOME/.config/herdr"
out=$(link_herdr_config 2>&1)
if [ -f "$HERDR_SRC" ] && [ ! -L "$HERDR_SRC" ] && [ "$(cat "$HERDR_SRC")" = "onboarding = false" ] \
   && [ ! -L "$HERDR_SRC" ] && case "$out" in *"linked into the dotfiles"*) true ;; *) false ;; esac; then
  pass "keeps the tracked config and warns about the dir link"
else
  fail "touched the tracked config behind a whole-dir link: $out"
fi
rm -rf "$FAKE_HOME/.config"

echo ""
echo "=== Test 35: symlink_config links config/ items but not herdr ==="
# An earlier test stubs symlink_config out; take the real one from install.sh.
eval "$(sed -n '/^symlink_config() {/,/^}/p' "$TESTDIR/install_patched.sh")"
mkdir -p "$DOTFILES/config/kitty"
rm -rf "$FAKE_HOME/.config"
symlink_config
if [ -L "$FAKE_HOME/.config/kitty" ] && [ ! -e "$FAKE_HOME/.config/herdr" ] && [ ! -L "$FAKE_HOME/.config/herdr" ]; then
  pass "links kitty and leaves ~/.config/herdr to link_herdr_config"
else
  fail "symlink_config touched ~/.config/herdr or skipped kitty"
fi
rm -rf "$DOTFILES/config/kitty" "$DOTFILES/config/herdr"
rm -rf "$FAKE_HOME/.config" "$FAKE_HOME/old_dotfiles"

echo ""
echo "=== Test 37: install_herdr upgrades herdr with whoever owns it, never a second copy ==="
# Stub-only PATH: the real herdr, pacman, yay, brew, curl and sh never run.
STUB_BIN="$TESTDIR/stub-bin"
STUB_LOG="$TESTDIR/stub.log"
STUB_OUT="$TESTDIR/stub-out.txt"
rm -rf "$STUB_BIN"
mkdir -p "$STUB_BIN"
for tool in mkdir dirname readlink cmp rm mv date ln cat grep awk sed tr cut head mktemp python3; do
  ln -s "$(command -v "$tool")" "$STUB_BIN/$tool"
done
# stub <tool> <body>: logs "<tool> <args>" to $STUB_LOG, then runs <body>.
stub() {
  rm -f "$STUB_BIN/$1"
  printf '#!/bin/bash\necho "%s $*" >> "%s"\n%s\n' "$1" "$STUB_LOG" "$2" > "$STUB_BIN/$1"
  chmod +x "$STUB_BIN/$1"
}
stub herdr 'if [ "$1 $2" = "integration status" ]; then echo "claude: current (v1) (x)"; fi'
stub pacman '[ "$STUB_OWNS" = 1 ]'
stub brew 'if [ "$1" = --prefix ]; then echo "$STUB_PREFIX"; fi'
stub yay 'true'
# curl serves latest.json (unless STUB_OFFLINE) and fails the installer download when STUB_DL_FAIL.
stub curl 'case "$*" in
  *latest.json*) [ "$STUB_OFFLINE" != 1 ] || exit 6; echo "{\"version\": \"$STUB_LATEST\"}" ;;
  *install.sh*) [ "$STUB_DL_FAIL" != 1 ] ;;
esac'
stub sh 'true'
stub sudo '"$@"'
stub herdr-app 'true'
stub pgrep '[ "$STUB_RUNNING" = 1 ]'
# Homebrew's prefix: its herdr link points at the Cellar binary.
STUB_PREFIX="$TESTDIR/brew-prefix"
mkdir -p "$STUB_PREFIX/bin"

# run_stubbed <OS> <owns 0|1> <command...>: runs with STUB_BIN as the only PATH.
# Its output lands in $STUB_OUT.
run_stubbed() {
  local os=$1 owns=$2
  shift 2
  : > "$STUB_LOG"
  (
    export PATH="$STUB_BIN" OS="$os" STUB_OWNS="$owns" STUB_PREFIX STUB_LATEST
    "$@"
  ) >"$STUB_OUT" 2>&1 || true
}
called() { grep -qxF -- "$1" "$STUB_LOG"; }
# fetched <url>: the installer was downloaded to a temp file (curl -o).
fetched() { grep -q -- "^curl -fsSL $1 -o " "$STUB_LOG"; }

run_stubbed Linux 0 install_herdr update
if called "herdr update" && ! called "yay -S --needed --noconfirm herdr-bin"; then
  pass "update runs herdr's own updater when pacman does not own it"
else
  fail "update did not run herdr update: $(tr '\n' ';' < "$STUB_LOG")"
fi

run_stubbed Linux 1 install_herdr update
if called "yay -S --needed --noconfirm herdr-bin" && ! called "herdr update"; then
  pass "update upgrades a pacman-owned herdr through yay"
else
  fail "pacman-owned herdr did not go through yay: $(tr '\n' ';' < "$STUB_LOG")"
fi

run_stubbed Linux 0 install_herdr
if ! called "herdr update" && ! called "yay -S --needed --noconfirm herdr-bin" &&
   ! fetched https://herdr.dev/install.sh; then
  pass "install leaves an installed herdr alone"
else
  fail "install touched an installed herdr: $(tr '\n' ';' < "$STUB_LOG")"
fi

rm -f "$STUB_BIN/herdr"
run_stubbed Linux 0 install_herdr
if fetched https://herdr.dev/install.sh && grep -q '^sh /' "$STUB_LOG" &&
   ! called "yay -S --needed --noconfirm herdr-bin"; then
  pass "installs a missing herdr with the official script on Linux, run from a temp file"
else
  fail "missing herdr did not use the official script: $(tr '\n' ';' < "$STUB_LOG")"
fi
stub curl 'case "$*" in *install.sh*) exit 22 ;; esac'
run_stubbed Linux 0 install_herdr
if ! grep -q '^sh ' "$STUB_LOG" && grep -q "WARNING: herdr install failed" "$STUB_OUT" &&
   grep -q "ERROR: Failed to download https://herdr.dev/install.sh" "$STUB_OUT"; then
  pass "a failed herdr download runs nothing and warns"
else
  fail "failed herdr download was not warned: $(tr '\n' ';' < "$STUB_OUT")"
fi
stub curl 'case "$*" in
  *latest.json*) [ "$STUB_OFFLINE" != 1 ] || exit 6; echo "{\"version\": \"$STUB_LATEST\"}" ;;
  *install.sh*) [ "$STUB_DL_FAIL" != 1 ] ;;
esac'

stub herdr 'if [ "$1 $2" = "integration status" ]; then echo "claude: current (v1) (x)"; fi'
# Owned by brew: PATH reaches the Cellar binary through brew's prefix link.
cp "$STUB_BIN/herdr" "$TESTDIR/cellar-herdr"
rm -f "$STUB_BIN/herdr" "$STUB_PREFIX/bin/herdr"
ln -s "$TESTDIR/cellar-herdr" "$STUB_PREFIX/bin/herdr"
ln -s "$STUB_PREFIX/bin/herdr" "$STUB_BIN/herdr"
run_stubbed Darwin 1 install_herdr update
if called "brew upgrade herdr" && ! called "herdr update"; then
  pass "update upgrades a brew-owned herdr through brew on macOS"
else
  fail "brew-owned herdr did not go through brew: $(tr '\n' ';' < "$STUB_LOG")"
fi

# A herdr on PATH that is not brew's link is not brew's, even with the formula installed.
stub herdr 'if [ "$1 $2" = "integration status" ]; then echo "claude: current (v1) (x)"; fi'
run_stubbed Darwin 1 install_herdr update
if called "herdr update" && ! called "brew upgrade herdr"; then
  pass "update runs herdr's own updater when PATH's herdr is not brew's link"
else
  fail "non-brew herdr on macOS did not run herdr update: $(tr '\n' ';' < "$STUB_LOG")"
fi

echo ""
echo "=== Test 38: install_herdr_app installs once, and update reruns the installer only when the version changed ==="
rm -f "$STUB_BIN/herdr-app"
STUB_LATEST=0.1.18
run_stubbed Linux 0 install_herdr_app
if called "sudo pacman -S --needed --noconfirm vulkan-icd-loader mesa libxkbcommon-x11 wayland" &&
   fetched https://releases.herdr.dev/app/install.sh; then
  pass "installs the Arch runtime libraries, then runs the app installer"
else
  fail "missing herdr-app did not install its deps and the app: $(tr '\n' ';' < "$STUB_LOG")"
fi

run_stubbed Darwin 0 install_herdr_app
if fetched https://releases.herdr.dev/app/install.sh && ! grep -q '^sudo' "$STUB_LOG"; then
  pass "installs herdr-app on macOS without the Arch libraries"
else
  fail "macOS herdr-app install ran pacman or skipped the app: $(tr '\n' ';' < "$STUB_LOG")"
fi

stub herdr-app 'echo "herdr-app 0.1.18"'
run_stubbed Linux 0 install_herdr_app
if [ ! -s "$STUB_LOG" ]; then
  pass "install skips herdr-app when it is already installed"
else
  fail "install touched an installed herdr-app: $(tr '\n' ';' < "$STUB_LOG")"
fi

run_stubbed Linux 0 install_herdr_app update
if ! fetched https://releases.herdr.dev/app/install.sh && ! grep -q '^sudo' "$STUB_LOG" &&
   grep -q "herdr-app 0.1.18 is current" "$STUB_OUT"; then
  pass "update leaves a current herdr-app alone"
else
  fail "update reinstalled a current herdr-app: $(tr '\n' ';' < "$STUB_LOG")"
fi

stub herdr-app 'echo "herdr-app 0.1.17"'
run_stubbed Linux 0 install_herdr_app update
if fetched https://releases.herdr.dev/app/install.sh && ! grep -q '^sudo' "$STUB_LOG"; then
  pass "update reruns the app installer when the version differs, without the libraries"
else
  fail "update did not rerun the app installer: $(tr '\n' ';' < "$STUB_LOG")"
fi

# A version of 0.1.1 must not match 0.1.18 by prefix.
stub herdr-app 'echo "herdr-app 0.1.1"'
run_stubbed Linux 0 install_herdr_app update
if fetched https://releases.herdr.dev/app/install.sh; then
  pass "compares whole versions, not prefixes"
else
  fail "0.1.1 was taken as current for 0.1.18: $(tr '\n' ';' < "$STUB_LOG")"
fi

stub herdr-app 'echo "herdr-app 0.1.17"'
STUB_OFFLINE=1 run_stubbed Linux 0 install_herdr_app update
if ! fetched https://releases.herdr.dev/app/install.sh && grep -q "skipping the update" "$STUB_OUT"; then
  pass "update skips herdr-app with a note when offline"
else
  fail "offline update did not skip: $(tr '\n' ';' < "$STUB_OUT")"
fi

STUB_RUNNING=1 run_stubbed Darwin 0 install_herdr_app update
if ! fetched https://releases.herdr.dev/app/install.sh && grep -q "Herdr is running" "$STUB_OUT"; then
  pass "macOS update leaves a running Herdr.app alone, with a note"
else
  fail "macOS update touched a running Herdr.app: $(tr '\n' ';' < "$STUB_OUT")"
fi

run_stubbed Darwin 0 install_herdr_app update
if fetched https://releases.herdr.dev/app/install.sh; then
  pass "macOS update reinstalls herdr-app when it is not running"
else
  fail "macOS update skipped a herdr-app that is not running: $(tr '\n' ';' < "$STUB_OUT")"
fi

STUB_DL_FAIL=1 run_stubbed Linux 0 install_herdr_app update
if ! grep -q '^sh ' "$STUB_LOG" && grep -q "WARNING: herdr-app install failed" "$STUB_OUT"; then
  pass "a failed herdr-app download runs nothing and warns"
else
  fail "failed herdr-app download was not warned: $(tr '\n' ';' < "$STUB_OUT")"
fi
rm -f "$STUB_BIN/herdr-app"
rm -rf "$STUB_PREFIX"

echo ""
echo "=== Test 39: cleanup_legacy removes and moves agent-deck and aoe, quietly the second time ==="
LEGACY_BK="$FAKE_HOME/old_dotfiles/legacy-session-managers-$(date +%Y%m%d)"
rm -rf "$FAKE_HOME/.local/bin" "$FAKE_HOME/.config/agent-deck" "$FAKE_HOME/.local/share/agent-deck" \
  "$FAKE_HOME/.cache/agent-deck" "$FAKE_HOME/.config/agent-of-empires" "$FAKE_HOME/.tmux.conf" \
  "$FAKE_HOME/.claude/skills/fleet" "$FAKE_HOME/.agents/skills/fleet" \
  "$FAKE_HOME/.claude/skills/agent-deck" "$FAKE_HOME/.agents/skills/agent-deck" \
  "$FAKE_HOME/.pi/agent/skills" "$FAKE_HOME/old_dotfiles"
mkdir -p "$FAKE_HOME/.local/bin" "$FAKE_HOME/.config/agent-deck" "$FAKE_HOME/.local/share/agent-deck" \
  "$FAKE_HOME/.cache/agent-deck" "$FAKE_HOME/.config/agent-of-empires" \
  "$FAKE_HOME/.claude/skills/fleet" "$FAKE_HOME/.agents/skills/fleet" \
  "$FAKE_HOME/.claude/skills/agent-deck" "$FAKE_HOME/.agents/skills/agent-deck" \
  "$FAKE_HOME/.pi/agent/skills"
touch "$FAKE_HOME/.local/bin/agent-deck" "$FAKE_HOME/.local/bin/aoe" "$FAKE_HOME/.local/bin/aoe (deleted)"
cat > "$FAKE_HOME/.tmux.conf" <<'CONF'

# agent-deck configuration
# agent-deck-tmux-config-version: 4
# Added by agent-deck installer - 2026-07-23
set -g mouse on
# End agent-deck configuration
CONF
for d in "$FAKE_HOME/.claude/skills/fleet" "$FAKE_HOME/.agents/skills/fleet" \
  "$FAKE_HOME/.claude/skills/agent-deck" "$FAKE_HOME/.agents/skills/agent-deck"; do
  echo "description: fan out agent-deck child sessions" > "$d/SKILL.md"
done
ln -s ../../../.agents/skills/fleet "$FAKE_HOME/.pi/agent/skills/fleet"
ln -s ../../../.agents/skills/agent-deck "$FAKE_HOME/.pi/agent/skills/agent-deck"

out=$(cleanup_legacy 2>&1)
if [ ! -e "$FAKE_HOME/.local/bin/agent-deck" ] && [ ! -e "$FAKE_HOME/.local/bin/aoe" ] &&
   [ ! -e "$FAKE_HOME/.local/bin/aoe (deleted)" ] &&
   [ -d "$LEGACY_BK/.config/agent-deck" ] && [ -d "$LEGACY_BK/.local/share/agent-deck" ] &&
   [ -d "$LEGACY_BK/.cache/agent-deck" ] && [ -d "$LEGACY_BK/.config/agent-of-empires" ] &&
   [ -f "$LEGACY_BK/.tmux.conf" ] && [ ! -e "$FAKE_HOME/.tmux.conf" ] &&
   [ ! -e "$FAKE_HOME/.config/agent-deck" ] && [ ! -e "$FAKE_HOME/.claude/skills/fleet" ] &&
   [ ! -e "$FAKE_HOME/.agents/skills/fleet" ] && [ ! -L "$FAKE_HOME/.pi/agent/skills/fleet" ] &&
   [ ! -e "$FAKE_HOME/.claude/skills/agent-deck" ] && [ ! -e "$FAKE_HOME/.agents/skills/agent-deck" ] &&
   [ ! -L "$FAKE_HOME/.pi/agent/skills/agent-deck" ]; then
  pass "removes binaries, fleet and agent-deck skills, moves config and tmux block, drops dangling pi links"
else
  fail "cleanup_legacy missed something: $out"
fi

out=$(cleanup_legacy 2>&1)
if [ -z "$out" ]; then
  pass "second run prints nothing"
else
  fail "second run was not quiet: $out"
fi

echo ""
echo "=== Test 40: cleanup_legacy keeps a tmux.conf with the user's lines and a foreign fleet skill ==="
rm -rf "$FAKE_HOME/old_dotfiles" "$FAKE_HOME/.claude/skills/fleet"
mkdir -p "$FAKE_HOME/.claude/skills/fleet"
echo "description: my own fleet skill" > "$FAKE_HOME/.claude/skills/fleet/SKILL.md"
mkdir -p "$FAKE_HOME/.agents/skills/agent-deck"
echo "description: my own deck tool" > "$FAKE_HOME/.agents/skills/agent-deck/SKILL.md"
cat > "$FAKE_HOME/.tmux.conf" <<'CONF'
set -g base-index 1

# agent-deck configuration
# Added by agent-deck installer - 2026-07-23
set -g mouse on
# End agent-deck configuration
CONF

out=$(cleanup_legacy 2>&1)
if [ -f "$FAKE_HOME/.tmux.conf" ] && [ ! -e "$FAKE_HOME/old_dotfiles" ] &&
   [ -f "$FAKE_HOME/.claude/skills/fleet/SKILL.md" ] &&
   [ -f "$FAKE_HOME/.agents/skills/agent-deck/SKILL.md" ] &&
   case "$out" in *"left as is"*) true ;; *) false ;; esac; then
  pass "keeps the mixed tmux.conf with a note and leaves fleet and agent-deck skills without agent-deck alone"
else
  fail "cleanup_legacy touched user content: $out"
fi
rm -rf "$FAKE_HOME/.tmux.conf" "$FAKE_HOME/.claude/skills/fleet" "$FAKE_HOME/.agents/skills/agent-deck"

echo ""
echo "=== Test 40b: the tmux block test rejects an unterminated second block ==="
TMUX_CONF="$TESTDIR/tmux.conf"
cat > "$TMUX_CONF" <<'CONF'
# agent-deck configuration
# Added by agent-deck installer - 2026-07-23
set -g mouse on
# End agent-deck configuration
# agent-deck configuration
set -g base-index 1
CONF
if _is_agent_deck_tmux_conf "$TMUX_CONF"; then
  fail "treated a file with an unterminated second block as agent-deck's alone"
else
  pass "keeps a file whose second agent-deck block never ends"
fi
cat > "$TMUX_CONF" <<'CONF'
# agent-deck configuration
# Added by agent-deck installer - 2026-07-23
set -g mouse on
# End agent-deck configuration
CONF
if _is_agent_deck_tmux_conf "$TMUX_CONF"; then
  pass "still treats a lone agent-deck block as agent-deck's"
else
  fail "rejected a lone agent-deck block"
fi

echo ""
echo "=== Test 40c: herdr repair leaves herdr-app installation to install, update and ai ==="
out=$(
  install_herdr() { echo "install_herdr"; }
  install_herdr_app() { echo "install_herdr_app"; }
  link_herdr_config() { echo "link_herdr_config"; }
  install_modules() { echo "install_modules"; }
  link_herdr_plugin() { echo "link_herdr_plugin"; }
  link_herdr_app() { echo "link_herdr_app"; }
  do_herdr
)
if ! grep -q "install_herdr_app" <<<"$out" && grep -q "install_modules" <<<"$out" && grep -q "link_herdr_app" <<<"$out"; then
  pass "herdr repair skips the herdr-app install and still runs the modules and links"
else
  fail "herdr repair installed herdr-app: $out"
fi

echo ""
echo "=== Test 41: cleanup_legacy does nothing when nothing is left ==="
out=$(cleanup_legacy 2>&1)
if [ -z "$out" ] && [ ! -e "$FAKE_HOME/old_dotfiles" ]; then
  pass "prints nothing and creates no backup dir"
else
  fail "cleanup_legacy was not a no-op: $out"
fi

echo ""
echo "=== Test 42: symlink never links AGENTS.md or CLAUDE.md into HOME ==="
# An earlier test stubs symlink out; take the real one from install.sh.
eval "$(sed -n '/^symlink() {/,/^}/p' "$TESTDIR/install_patched.sh")"
touch "$DOTFILES/AGENTS.md" "$DOTFILES/CLAUDE.md" "$DOTFILES/zz-probe"
rm -f "$FAKE_HOME/.AGENTS.md" "$FAKE_HOME/.CLAUDE.md" "$FAKE_HOME/.zz-probe"
# symlink ends each excluded entry with in_array's 1, which the harness's set -e
# would take as a failure; the assertions below check what it did.
symlink || true
if [ ! -e "$FAKE_HOME/.AGENTS.md" ] && [ ! -L "$FAKE_HOME/.AGENTS.md" ] &&
   [ ! -e "$FAKE_HOME/.CLAUDE.md" ] && [ ! -L "$FAKE_HOME/.CLAUDE.md" ] &&
   [ -L "$FAKE_HOME/.zz-probe" ]; then
  pass "skips AGENTS.md and CLAUDE.md, still links other dotfiles"
else
  fail "symlink linked AGENTS.md or CLAUDE.md into HOME"
fi
rm -f "$DOTFILES/AGENTS.md" "$DOTFILES/CLAUDE.md" "$DOTFILES/zz-probe" \
  "$FAKE_HOME/.zz-probe"
rm -rf "$FAKE_HOME/old_dotfiles"

echo ""
echo "=== ALL TESTS COMPLETE ==="
