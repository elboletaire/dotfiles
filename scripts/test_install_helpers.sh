#!/bin/bash
# Regression tests for scripts/install.sh helpers.
# Uses a fake HOME and a mock apm binary; never touches the real home or system.
set -euo pipefail

# ── colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}PASS${NC} $*"; }
fail() { echo -e "  ${RED}FAIL${NC} $*"; exit 1; }
info() { echo -e "  ${CYAN}INFO${NC} $*"; }

TESTDIR="$(mktemp -d)"
trap 'rm -rf "$TESTDIR"' EXIT

FAKE_HOME="$TESTDIR/home"
mkdir -p "$FAKE_HOME/.apm"
export HOME="$FAKE_HOME"

DOTFILES="$TESTDIR/dotfiles"
mkdir -p "$DOTFILES/ai"
mkdir -p "$DOTFILES/scripts"

# ── mock apm v0.28.0 ──────────────────────────────────────────────────────
MOCK_APM="$TESTDIR/bin/apm"
mkdir -p "$(dirname "$MOCK_APM")"
cat > "$MOCK_APM" <<'MOCK'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install)
    # Simulate installing a local package: deploy skills listed in the manifest.
    # Creates skill dirs in .agents/skills/ and .claude/skills/ for each
    # dependency implied by the local package's apm.yml + lockfile.
    local_pkg="${*: -1}"  # last arg is the local package path
    if [ "$local_pkg" = "-g" ]; then
      local_pkg="${!#}"  # last arg when -g is present
    fi
    mkdir -p "$HOME/.agents/skills/test-skill"
    mkdir -p "$HOME/.claude/skills"
    ln -sf "$HOME/.agents/skills/test-skill" "$HOME/.claude/skills/test-skill"
    # APM appends to global manifest; it does NOT overwrite unrelated entries.
    # Simulate adding a section for the dotfiles local package.
    if [ -f "$HOME/.apm/apm.yml" ]; then
      echo "# existing global entry preserved" >> "$HOME/.apm/apm.yml"
    else
      echo "name: global-manifest" > "$HOME/.apm/apm.yml"
    fi
    exit 0 ;;
  update)
    mkdir -p "$HOME/.agents/skills/test-skill-updated"
    mkdir -p "$HOME/.claude/skills"
    ln -sf "$HOME/.agents/skills/test-skill-updated" "$HOME/.claude/skills/test-skill-updated"
    # Simulate apm update writing back apm.yml + lock
    echo "name: dotfiles-skills" > "$HOME/.apm/apm.yml"
    echo "lockfile_version: '1'" > "$HOME/.apm/apm.lock.yaml"
    echo "# updated" >> "$HOME/.apm/apm.lock.yaml"
    exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK
chmod +x "$MOCK_APM"

OLD_PATH="$PATH"
export PATH="$(dirname "$MOCK_APM"):$OLD_PATH"

# ── source install.sh functions ────────────────────────────────────────────
cp "$(cd "$(dirname "$0")/.." && pwd)/scripts/install.sh" "$DOTFILES/scripts/install.sh"

# Patch dotfiles dir for test env
sed "s|declare -r dotfiles=~/.dotfiles|declare -r dotfiles=$DOTFILES|" \
  "$DOTFILES/scripts/install.sh" > "$TESTDIR/install_patched.sh"

source "$TESTDIR/install_patched.sh"

echo ""
echo "=== Test 1: bash -n syntax check ==="
if bash -n "$DOTFILES/scripts/install.sh" 2>&1; then
  pass "install.sh passes bash -n"
else
  fail "install.sh has syntax errors"
fi

echo ""
echo "=== Test 2: install_apm when apm already present ==="
if install_apm 2>&1 | grep -q "already installed"; then
  pass "install_apm detects existing apm"
else
  fail "install_apm should have detected existing apm"
fi

echo ""
echo "=== Test 3: symlink_ai uses single apm install -g with comma-separated multi-target ==="
# Create a minimal tracked lockfile with exactly 3 skill names
cat > "$DOTFILES/ai/apm.yml" <<'YML'
name: dotfiles-skills
version: 1.0.0
targets:
  - agent-skills
  - claude
dependencies:
  apm:
    - git: https://github.com/test-owner/test-repo.git
      path: skills/test-skill
      alias: test-skill
      ref: abc123def456
YML
cat > "$DOTFILES/ai/apm.lock.yaml" <<'LOCK'
lockfile_version: '1'
apm_version: 0.28.0
dependencies:
- repo_url: test-owner/test-repo
  name: test-skill
  host: github.com
  resolved_commit: abc123def456
  version: unknown
  virtual_path: skills/test-skill
  is_virtual: true
  package_type: claude_skill
  deployed_files:
  - .agents/skills/test-skill
  - .agents/skills/test-skill/SKILL.md
  - .claude/skills/test-skill
  - .claude/skills/test-skill/SKILL.md
LOCK
rm -f "$FAKE_HOME/.apm/apm.yml" "$FAKE_HOME/.apm/apm.lock.yaml" "$FAKE_HOME/.apm/mock.log"

# Place legacy symlinks that should be cleaned BEFORE apm install
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"
mkdir -p "$FAKE_HOME/.agents/skills/test-skill"
ln -sf "$FAKE_HOME/.agents/skills/test-skill" "$FAKE_HOME/.pi/agent/skills/test-skill"
ln -sf "$FAKE_HOME/.agents/skills/test-skill" "$FAKE_HOME/.claude/skills/test-skill"

symlink_ai

# Verify legacy symlink was cleaned BEFORE apm install
if [ ! -L "$FAKE_HOME/.pi/agent/skills/test-skill" ]; then
  pass "Legacy symlink cleaned before APM install"
else
  fail "Legacy symlink should have been cleaned"
fi

# Verify a single apm install -g was invoked with comma-separated --target
if grep -q "apm install -g $DOTFILES/ai --target agent-skills,claude" "$FAKE_HOME/.apm/mock.log" 2>/dev/null; then
  pass "Single apm install -g with --target agent-skills,claude was invoked"
else
  fail "apm install -g --target agent-skills,claude not found in mock log"
fi
# Verify only ONE install invocation happened (not two)
install_count=$(awk '/apm install/{count++} END {print count+0}' "$FAKE_HOME/.apm/mock.log")
if [ "$install_count" -eq 1 ]; then
  pass "Exactly one apm install invocation (not two)"
else
  fail "Expected 1 apm install invocation, got $install_count"
fi

echo ""
echo "=== Test 4: unrelated ~/.apm/apm.yml content is not overwritten ==="
# Prepopulate ~/.apm/apm.yml with unrelated content
echo "# unrelated global APM entry" > "$FAKE_HOME/.apm/apm.yml"
echo "name: some-other-global-package" >> "$FAKE_HOME/.apm/apm.yml"

# Add a mock that appends rather than overwrites for this test
cat > "$MOCK_APM" <<'MOCK4'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install)
    # APM appends new entries rather than overwriting the global manifest
    echo "# dotfiles entry added by apm" >> "$HOME/.apm/apm.yml"
    mkdir -p "$HOME/.agents/skills/test-skill"
    mkdir -p "$HOME/.claude/skills"
    exit 0 ;;
  update)
    exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK4

rm -f "$FAKE_HOME/.apm/mock.log"
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"
symlink_ai

# Check the original content survived
if grep -q "unrelated global APM entry" "$FAKE_HOME/.apm/apm.yml" 2>/dev/null; then
  pass "Unrelated ~/.apm/apm.yml content preserved"
else
  fail "Unrelated ~/.apm/apm.yml content was overwritten"
fi

echo ""
echo "=== Test 4b: an existing local package gets a fresh global graph ==="
cat > "$FAKE_HOME/.apm/apm.yml" <<GLOBAL4B
name: home
dependencies:
  apm:
    - unrelated/package
    - $DOTFILES/ai
GLOBAL4B
cat > "$FAKE_HOME/.apm/apm.lock.yaml" <<GLOBALLOCK4B
lockfile_version: '1'
dependencies:
- repo_url: _local/ai
  name: dotfiles-skills
  local_path: $DOTFILES/ai
- repo_url: owner/retired-repo
  name: retired-skill
  resolved_by: _local/ai
- repo_url: unrelated/package
  name: unrelated-skill
GLOBALLOCK4B
mkdir -p "$FAKE_HOME/.agents/skills/retired-skill"
mkdir -p "$FAKE_HOME/.claude/skills/retired-skill"
mkdir -p "$FAKE_HOME/.agents/skills/unrelated-skill"
cat > "$MOCK_APM" <<'MOCK4B'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  uninstall) exit 0 ;;
  install)
    if [ "${2:-}" = "-g" ]; then
      if [ -e "$HOME/.apm/apm.lock.yaml" ]; then
        echo "Global install must rebuild without replaying the stale lock" >&2
        exit 1
      fi
      printf '%s\n' "lockfile_version: '1'" > "$HOME/.apm/apm.lock.yaml"
    fi
    exit 0 ;;
  prune) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK4B
rm -f "$FAKE_HOME/.apm/mock.log"
symlink_ai
expected_sync=$(printf '%s\n%s' \
  "apm uninstall -g $DOTFILES/ai" \
  "apm install -g $DOTFILES/ai --target agent-skills,claude")
actual_sync=$(grep '^apm \(uninstall -g\|install -g\) ' "$FAKE_HOME/.apm/mock.log")
if [ "$actual_sync" = "$expected_sync" ]; then
  pass "Existing package cache is removed before rebuilding its flattened graph"
else
  fail "Expected uninstall/fresh-install sequence, got: $actual_sync"
fi
if ! grep -q 'name: retired-skill' "$FAKE_HOME/.apm/apm.lock.yaml"; then
  pass "Fresh global lock no longer records the retired dependency"
else
  fail "Fresh global lock should not retain the retired dependency"
fi
if [ ! -e "$FAKE_HOME/.agents/skills/retired-skill" ] && \
   [ ! -e "$FAKE_HOME/.claude/skills/retired-skill" ]; then
  pass "Retired skills previously owned by the dotfiles package are pruned"
else
  fail "Retired dotfiles skill directories should be pruned after replacement"
fi
if [ -d "$FAKE_HOME/.agents/skills/unrelated-skill" ]; then
  pass "Unrelated skill directories are preserved during retired-skill cleanup"
else
  fail "Unrelated skill directory should be preserved"
fi
# Keep later tests independent of the installed-package branch.
printf '%s\n' 'name: home' 'dependencies:' '  apm:' '    - unrelated/package' > "$FAKE_HOME/.apm/apm.yml"

echo ""
echo "=== Test 5: legacy cleanup only removes lock-owned symlinks ==="
# Restore mock apm for install
cat > "$MOCK_APM" <<'MOCK5'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install)
    mkdir -p "$HOME/.agents/skills/test-skill"
    exit 0 ;;
  update) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK5

# Setup: tracked skill is "test-skill", but we also have foreign entries
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"
mkdir -p "$FAKE_HOME/.agents/skills/test-skill"
mkdir -p "$FAKE_HOME/.agents/skills/foreign-skill"
mkdir -p "$FAKE_HOME/foreign-dir"

# Managed legacy symlink (basename matches tracked skill, target in ~/.agents/skills)
ln -sf "$FAKE_HOME/.agents/skills/test-skill" "$FAKE_HOME/.pi/agent/skills/test-skill"
ln -sf "$FAKE_HOME/.agents/skills/test-skill" "$FAKE_HOME/.claude/skills/test-skill"

# Foreign symlink (basename NOT in tracked skills)
ln -sf "$FAKE_HOME/.agents/skills/foreign-skill" "$FAKE_HOME/.pi/agent/skills/foreign-skill"

# Foreign symlink pointing outside ~/.agents/skills
ln -sf "$FAKE_HOME/foreign-dir" "$FAKE_HOME/.pi/agent/skills/external-link"

# Regular directory (not a symlink) - should survive
mkdir -p "$FAKE_HOME/.pi/agent/skills/custom-dir"

# Dangling managed symlink: basename matches a tracked skill, target points
# into ~/.agents/skills but the target directory no longer exists.
mkdir -p "$FAKE_HOME/.agents/skills/will-be-deleted"
ln -sf "$FAKE_HOME/.agents/skills/will-be-deleted" "$FAKE_HOME/.pi/agent/skills/will-be-deleted"
rm -rf "$FAKE_HOME/.agents/skills/will-be-deleted"  # now dangling

# Update lockfile to include will-be-deleted as a tracked skill name
cat > "$DOTFILES/ai/apm.lock.yaml" <<'LOCK5'
lockfile_version: '1'
apm_version: 0.28.0
dependencies:
- repo_url: test-owner/test-repo
  name: test-skill
  resolved_commit: abc123def456
  virtual_path: skills/test-skill
  is_virtual: true
- repo_url: test-owner/another-repo
  name: will-be-deleted
  resolved_commit: xyz789
  virtual_path: skills/will-be-deleted
  is_virtual: true
LOCK5

rm -f "$FAKE_HOME/.apm/mock.log"

clean_legacy_skill_symlinks "$DOTFILES/ai/apm.lock.yaml"

# Managed symlink removed
if [ ! -L "$FAKE_HOME/.pi/agent/skills/test-skill" ]; then
  pass "Managed pi symlink removed"
else
  fail "Managed pi symlink should have been removed"
fi
if [ ! -L "$FAKE_HOME/.claude/skills/test-skill" ]; then
  pass "Managed claude symlink removed"
else
  fail "Managed claude symlink should have been removed"
fi

# Foreign symlink (untracked basename) preserved
if [ -L "$FAKE_HOME/.pi/agent/skills/foreign-skill" ]; then
  pass "Foreign symlink (untracked name) preserved"
else
  fail "Foreign symlink should have been preserved"
fi

# Foreign symlink (external target) preserved
if [ -L "$FAKE_HOME/.pi/agent/skills/external-link" ]; then
  pass "Foreign symlink (external target) preserved"
else
  fail "Foreign symlink (external target) should have been preserved"
fi

# Regular directory preserved
if [ -d "$FAKE_HOME/.pi/agent/skills/custom-dir" ]; then
  pass "Custom directory preserved"
else
  fail "Custom directory should have been preserved"
fi

# Check that will-be-deleted was cleaned even though its target was deleted
if [ ! -L "$FAKE_HOME/.pi/agent/skills/will-be-deleted" ]; then
  pass "Dangling managed symlink removed"
else
  fail "Dangling managed symlink should have been removed (basename in lock, target path in ~/.agents/skills)"
fi

echo ""
echo "=== Test 6: foreign regular ~/.agents/.skill-lock.json survives ==="
# Reset mock APM
cat > "$MOCK_APM" <<'MOCK6'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install) exit 0 ;;
  update) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK6

# Create a foreign regular-file .skill-lock.json (not a symlink)
echo '{"foreign":true}' > "$FAKE_HOME/.agents/.skill-lock.json"
rm -f "$FAKE_HOME/.apm/mock.log"
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"

symlink_ai

if [ -f "$FAKE_HOME/.agents/.skill-lock.json" ] && [ ! -L "$FAKE_HOME/.agents/.skill-lock.json" ]; then
  if grep -q "foreign" "$FAKE_HOME/.agents/.skill-lock.json" 2>/dev/null; then
    pass "Foreign regular .skill-lock.json preserved unchanged"
  else
    fail "Foreign regular .skill-lock.json content changed"
  fi
else
  fail "Foreign regular .skill-lock.json should have survived (not a symlink)"
fi

echo ""
echo "=== Test 7: ~/.agents/.skill-lock.json symlink removed after successful install ==="
# Now create it as a symlink
rm -f "$FAKE_HOME/.agents/.skill-lock.json"
ln -sf "$DOTFILES/ai/some-lock.json" "$FAKE_HOME/.agents/.skill-lock.json"
rm -f "$FAKE_HOME/.apm/mock.log"
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"

symlink_ai

if [ ! -L "$FAKE_HOME/.agents/.skill-lock.json" ] && [ ! -e "$FAKE_HOME/.agents/.skill-lock.json" ]; then
  pass "Legacy skill-lock symlink removed after successful APM install"
else
  fail "Legacy skill-lock symlink should have been removed"
fi

echo ""
echo "=== Test 8: APM install failure returns nonzero and does not print success ==="
# Mock APM that fails on install
cat > "$MOCK_APM" <<'MOCK8'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install) echo "Mock APM install failure" >&2; exit 1 ;;
  update) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK8

rm -f "$FAKE_HOME/.apm/mock.log"
rm -f "$FAKE_HOME/.agents/.skill-lock.json"
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"

# Capture output and exit status
set +e
output=$(symlink_ai 2>&1)
symlink_ai_rc=$?
set -e

if [ "$symlink_ai_rc" -ne 0 ]; then
  pass "symlink_ai returns nonzero on APM install failure (rc=$symlink_ai_rc)"
else
  fail "symlink_ai should return nonzero on APM install failure (rc=$symlink_ai_rc)"
fi

# Should print error, not success
if echo "$output" | grep -q "ERROR"; then
  pass "Error message printed on failure"
else
  fail "Should print error message on failure"
fi

if ! echo "$output" | grep -q "successful"; then
  pass "No success message on failure"
else
  fail "Should not print success on failure"
fi

# skill-lock.json should NOT be removed when APM install fails
# (setup: create a symlink skill-lock.json, then try symlink_ai which should fail)
# Only if we created it above... Actually the test already removed it. Let's create one here.
ln -sf "$DOTFILES/ai/some-lock.json" "$FAKE_HOME/.agents/.skill-lock.json"
rm -f "$FAKE_HOME/.apm/mock.log"
set +e
symlink_ai 2>&1 > /dev/null
set -e
if [ -L "$FAKE_HOME/.agents/.skill-lock.json" ]; then
  pass "skill-lock.json symlink preserved when APM install fails"
else
  fail "skill-lock.json symlink should NOT be removed when APM install fails"
fi

echo ""
echo "=== Test 9: refresh leaves tracked files unchanged when APM validation fails ==="
# Mock Git resolves a new default-branch commit; APM install then fails.
git() {
  if [ "${1:-}" = "ls-remote" ]; then
    printf '%s\tHEAD\n' '1111111111111111111111111111111111111111'
    return 0
  fi
  command git "$@"
}
cat > "$MOCK_APM" <<'MOCK9'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install) echo "Mock APM validation failure" >&2; exit 1 ;;
  update) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK9

cat > "$DOTFILES/ai/apm.yml" <<'YML9'
name: dotfiles-skills
targets: [agent-skills, claude]
dependencies:
  apm:
    - git: https://github.com/test-owner/test-repo.git
      path: skills/test-skill
      alias: test-skill
      ref: 0000000000000000000000000000000000000000
YML9
echo "# track-before-update" > "$DOTFILES/ai/apm.lock.yaml"
manifest_before=$(cat "$DOTFILES/ai/apm.yml")
lock_before=$(cat "$DOTFILES/ai/apm.lock.yaml")
rm -f "$FAKE_HOME/.apm/mock.log"

set +e
update_output=$(update_apm_skills 2>&1)
update_rc=$?
set -e

if [ "$update_rc" -ne 0 ]; then
  pass "update_apm_skills returns nonzero on APM validation failure (rc=$update_rc)"
else
  fail "update_apm_skills should return nonzero on validation failure"
fi
if [ "$(cat "$DOTFILES/ai/apm.yml")" = "$manifest_before" ]; then
  pass "ai/apm.yml unchanged after failed refresh"
else
  fail "ai/apm.yml should be unchanged after failed refresh"
fi
if [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = "$lock_before" ]; then
  pass "ai/apm.lock.yaml unchanged after failed refresh"
else
  fail "ai/apm.lock.yaml should be unchanged after failed refresh"
fi

echo ""
echo "=== Test 9b: tracked manifest and lock update as one transaction ==="
cat > "$MOCK_APM" <<'MOCK9B'
#!/bin/bash
case "${1:-}" in
  install)
    printf '%s\n' "lockfile_version: '1'" '# rebuilt-by-apm' > apm.lock.yaml
    exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK9B
cat > "$DOTFILES/ai/apm.yml" <<'YML9B'
name: dotfiles-skills
targets: [agent-skills, claude]
dependencies:
  apm:
    - git: https://github.com/test-owner/test-repo.git
      alias: test-skill
      ref: 0000000000000000000000000000000000000000
YML9B
echo "# original-lock" > "$DOTFILES/ai/apm.lock.yaml"
manifest_before=$(cat "$DOTFILES/ai/apm.yml")
lock_before=$(cat "$DOTFILES/ai/apm.lock.yaml")
cp_fail_once=1
cp() {
  if [ "$cp_fail_once" -eq 1 ] && [[ "${1:-}" == */apm.lock.yaml ]] && \
    { [ "${2:-}" = "$DOTFILES/ai/apm.lock.yaml" ] || [[ "${2:-}" == *.new ]]; }; then
    cp_fail_once=0
    return 1
  fi
  command cp "$@"
}
set +e
transaction_output=$(update_apm_skills 2>&1)
transaction_rc=$?
set -e
unset -f cp
if [ "$transaction_rc" -ne 0 ]; then
  pass "update_apm_skills reports a failed second-file write"
else
  fail "update_apm_skills should fail when the lockfile cannot be staged"
fi
if [ "$(cat "$DOTFILES/ai/apm.yml")" = "$manifest_before" ] && \
   [ "$(cat "$DOTFILES/ai/apm.lock.yaml")" = "$lock_before" ]; then
  pass "Failed write leaves both tracked APM files unchanged"
else
  fail "Manifest and lock must remain in their original matched state"
fi

echo ""
echo "=== Test 10: refresh resolves HEAD, validates with APM, and updates tracked state ==="
cat > "$MOCK_APM" <<'MOCK10'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install)
    echo "lockfile_version: '1'" > "apm.lock.yaml"
    echo "# rebuilt-by-apm" >> "apm.lock.yaml"
    exit 0 ;;
  update) echo "apm update must not be used for revision pins" >&2; exit 1 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK10

cat > "$DOTFILES/ai/apm.yml" <<'YML10'
name: dotfiles-skills
targets: [agent-skills, claude]
dependencies:
  apm:
    - git: https://github.com/test-owner/test-repo.git
      path: skills/test-skill
      alias: test-skill
      ref: 0000000000000000000000000000000000000000
YML10
echo "# old-lock" > "$DOTFILES/ai/apm.lock.yaml"
rm -f "$FAKE_HOME/.apm/mock.log"

update_apm_skills

if grep -q 'ref: 1111111111111111111111111111111111111111' "$DOTFILES/ai/apm.yml"; then
  pass "Manifest ref updated to the resolved default-branch commit"
else
  fail "Manifest ref was not refreshed"
fi
if grep -q "rebuilt-by-apm" "$DOTFILES/ai/apm.lock.yaml"; then
  pass "APM rebuilt the tracked lock after ref refresh"
else
  fail "APM lock was not rebuilt after ref refresh"
fi
if grep -q "apm install --target agent-skills,claude" "$FAKE_HOME/.apm/mock.log"; then
  pass "Refresh validates the new pins with a project-scoped APM install"
else
  fail "Refresh did not run the expected project-scoped APM validation"
fi
if grep -q "apm install -g" "$FAKE_HOME/.apm/mock.log"; then
  fail "update_apm_skills should not perform a redundant global install"
else
  pass "update_apm_skills leaves the single global sync to symlink_ai"
fi

echo ""
echo "=== Test 11: function existence checks ==="
if declare -f install_apm &>/dev/null; then
  pass "install_apm exists"
else
  fail "install_apm missing"
fi
if declare -f clean_legacy_skill_symlinks &>/dev/null; then
  pass "clean_legacy_skill_symlinks exists"
else
  fail "clean_legacy_skill_symlinks missing"
fi
if declare -f update_apm_skills &>/dev/null; then
  pass "update_apm_skills exists"
else
  fail "update_apm_skills missing"
fi
if declare -f symlink_ai &>/dev/null; then
  pass "symlink_ai exists"
else
  fail "symlink_ai missing"
fi

echo ""
echo "=== Test 12: old npx skills functions removed ==="
if declare -f link_skill_lock &>/dev/null; then
  fail "link_skill_lock should have been removed"
else
  pass "link_skill_lock removed"
fi
if declare -f update_skills &>/dev/null; then
  fail "update_skills should have been removed"
else
  pass "update_skills removed"
fi

echo ""
echo "=== Test 13: apm version reports 0.28.0 ==="
version=$(apm --version 2>&1)
if [[ "$version" == "0.28.0" ]]; then
  pass "mock APM reports v0.28.0"
else
  fail "mock APM should report v0.28.0, got: $version"
fi

echo ""
echo "=== Test 14: tracked skill name derivation from lockfile (internal _tracked_skill_names) ==="
cat > "$DOTFILES/ai/apm.lock.yaml" <<'LOCK14'
lockfile_version: '1'
apm_version: 0.28.0
dependencies:
- repo_url: owner/repo-a
  name: skill-alpha
  resolved_commit: aaaaaa
- repo_url: owner/repo-b
  name: skill-beta
  resolved_commit: bbbbbb
- repo_url: owner/repo-c
  name: skill-gamma
  resolved_commit: cccccc
LOCK14

names=$(_tracked_skill_names "$DOTFILES/ai/apm.lock.yaml")
expected_count=$(echo "$names" | wc -l)
if [ "$expected_count" -eq 3 ]; then
  pass "Tracked skill names: 3 extracted"
else
  fail "Expected 3 skill names, got $expected_count"
fi

if echo "$names" | grep -qxF "skill-alpha" && \
   echo "$names" | grep -qxF "skill-beta" && \
   echo "$names" | grep -qxF "skill-gamma"; then
  pass "All tracked skill names match lockfile entries"
else
  fail "Tracked skill names mismatch; got: $(echo "$names" | tr '\n' ' ')"
fi

echo ""
echo "=== Test 15: do_install propagates APM failure, no success message ==="
# Mock APM that fails on install
cat > "$MOCK_APM" <<'MOCK15'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install) echo "Mock APM install failure" >&2; exit 1 ;;
  update) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK15

# Override functions that shouldn't actually run during this test
install_packages() { return 0; }
install_nvm() { return 0; }
install_ai_agents() { return 0; }
install_aoe() { return 0; }
install_rtk() { return 0; }
symlink() { return 0; }
symlink_config() { return 0; }
git() { return 0; }
chsh() { return 0; }
vim() { return 0; }
which() { echo "/usr/bin/zsh"; }

rm -f "$FAKE_HOME/.apm/mock.log"
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"

set +e
do_install_output=$(do_install 2>&1)
do_install_rc=$?
set -e

if [ "$do_install_rc" -ne 0 ]; then
  pass "do_install returns nonzero on APM failure (rc=$do_install_rc)"
else
  fail "do_install should return nonzero on APM failure"
fi

if ! echo "$do_install_output" | grep -q "was successful"; then
  pass "do_install does not print success on APM failure"
else
  fail "do_install should not print success on APM failure"
fi

echo ""
echo "=== Test 16: do_update propagates APM failure, no success message ==="
# Re-use failing mock from test 15
rm -f "$FAKE_HOME/.apm/mock.log"

set +e
do_update_output=$(do_update 2>&1)
do_update_rc=$?
set -e

if [ "$do_update_rc" -ne 0 ]; then
  pass "do_update returns nonzero on APM failure (rc=$do_update_rc)"
else
  fail "do_update should return nonzero on APM failure"
fi

if ! echo "$do_update_output" | grep -q "update complete"; then
  pass "do_update does not print success on APM failure"
else
  fail "do_update should not print success on APM failure"
fi

echo ""
echo "=== Test 17: do_update_ai propagates APM failure, no success message ==="
rm -f "$FAKE_HOME/.apm/mock.log"

set +e
do_update_ai_output=$(do_update_ai 2>&1)
do_update_ai_rc=$?
set -e

if [ "$do_update_ai_rc" -ne 0 ]; then
  pass "do_update_ai returns nonzero on APM failure (rc=$do_update_ai_rc)"
else
  fail "do_update_ai should return nonzero on APM failure"
fi

if ! echo "$do_update_ai_output" | grep -q "AI stack update complete"; then
  pass "do_update_ai does not print success on APM failure"
else
  fail "do_update_ai should not print success on APM failure"
fi

echo ""
echo "=== Test 18: symlink_ai rollback restores managed symlinks on APM failure ==="
# Mock APM that succeeds for cleanup but fails on install
cat > "$MOCK_APM" <<'MOCK18'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install) echo "Mock APM install failure" >&2; exit 1 ;;
  update) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK18

# Setup test-skill as a tracked skill in lockfile
cat > "$DOTFILES/ai/apm.lock.yaml" <<'LOCK18'
lockfile_version: '1'
apm_version: 0.28.0
dependencies:
- repo_url: test-owner/test-repo
  name: test-skill
  resolved_commit: abc123def456
  virtual_path: skills/test-skill
  is_virtual: true
LOCK18

# Create managed symlinks that will be cleaned
rm -rf "$FAKE_HOME/.pi/agent/skills"
rm -rf "$FAKE_HOME/.claude/skills"
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"
mkdir -p "$FAKE_HOME/.agents/skills/test-skill"
ln -sf "$FAKE_HOME/.agents/skills/test-skill" "$FAKE_HOME/.pi/agent/skills/test-skill"
ln -sf "$FAKE_HOME/.agents/skills/test-skill" "$FAKE_HOME/.claude/skills/test-skill"

rm -f "$FAKE_HOME/.apm/mock.log"

set +e
symlink_ai 2>&1 > /dev/null
set -e

# After failed symlink_ai, managed symlinks should be RESTORED
if [ -L "$FAKE_HOME/.pi/agent/skills/test-skill" ]; then
  pass "Managed pi symlink restored after APM install failure"
else
  fail "Managed pi symlink should have been restored after APM failure"
fi
if [ -L "$FAKE_HOME/.claude/skills/test-skill" ]; then
  pass "Managed claude symlink restored after APM install failure"
else
  fail "Managed claude symlink should have been restored after APM failure"
fi

echo ""
echo "=== Test 19: symlink_ai rollback does not overwrite existing files ==="
# Mock APM fails
cat > "$MOCK_APM" <<'MOCK19'
#!/bin/bash
echo "apm $*" >> "$HOME/.apm/mock.log"
case "${1:-}" in
  install) echo "Mock APM install failure" >&2; exit 1 ;;
  update) exit 0 ;;
  --version) echo "0.28.0"; exit 0 ;;
  *) exit 0 ;;
esac
MOCK19

# Setup: managed symlink exists but someone placed a regular file at the link path
# after cleanup (simulating a race or parallel install)
rm -rf "$FAKE_HOME/.pi/agent/skills"
rm -rf "$FAKE_HOME/.claude/skills"
mkdir -p "$FAKE_HOME/.pi/agent/skills"
mkdir -p "$FAKE_HOME/.claude/skills"
mkdir -p "$FAKE_HOME/.agents/skills/test-skill"
ln -sf "$FAKE_HOME/.agents/skills/test-skill" "$FAKE_HOME/.pi/agent/skills/test-skill"
echo "foreign content" > "$FAKE_HOME/.claude/skills/test-skill"  # regular file, not symlink

rm -f "$FAKE_HOME/.apm/mock.log"

set +e
symlink_ai 2>&1 > /dev/null
set -e

# pi symlink should be restored (path was free)
if [ -L "$FAKE_HOME/.pi/agent/skills/test-skill" ]; then
  pass "Rollback restores pi symlink when path is free"
else
  fail "Rollback should have restored pi symlink"
fi

# claude path has a regular file now - rollback must NOT overwrite
if [ -f "$FAKE_HOME/.claude/skills/test-skill" ] && [ ! -L "$FAKE_HOME/.claude/skills/test-skill" ]; then
  if grep -q "foreign content" "$FAKE_HOME/.claude/skills/test-skill"; then
    pass "Rollback preserves foreign regular file at claude path"
  else
    fail "Rollback should have preserved foreign file contents"
  fi
else
  fail "Rollback should NOT have overwritten existing regular file at claude path"
fi

echo ""
echo "=== Test 20: install_apm Linux path uses temp file, not pipe ==="
# Source-level check: the Linux branch should not contain a pipeline with curl|bash
install_sh="$DOTFILES/scripts/install.sh"
if grep -A 15 '^install_apm()' "$install_sh" | grep -q 'curl.*|.*bash'; then
  fail "install_apm should not pipe curl into bash"
else
  pass "install_apm uses temp-file download, not pipe"
fi

echo ""
echo "=== Test 21: update_apm_skills has no persistent RETURN trap ==="
# The function must use explicit cleanup, not 'trap ... RETURN'
if grep -A 5 '^update_apm_skills()' "$install_sh" | grep -q 'trap.*RETURN'; then
  fail "update_apm_skills should not use trap RETURN"
else
  pass "update_apm_skills uses explicit cleanup (no trap RETURN)"
fi

echo ""
echo "=== Test 22: _tracked_skill_names parses real lockfile with portable regex ==="
# Use the real lockfile from the project (not the test copy that may be overwritten)
REAL_LOCKFILE="$(cd "$(dirname "$0")/.." && pwd)/ai/apm.lock.yaml"
if [ -f "$REAL_LOCKFILE" ]; then
  names=$(_tracked_skill_names "$REAL_LOCKFILE")
  count=$(echo "$names" | wc -l)
  if [ "$count" -eq 16 ]; then
    pass "Real lockfile: exactly 16 skill names extracted"
  else
    fail "Real lockfile: expected exactly 16 skill names, got $count"
  fi
else
  pass "Real lockfile not available at $REAL_LOCKFILE; synthetic test already passed"
fi

# Verify the regex used is portable (no \s)
if grep '^_tracked_skill_names()' -A 5 "$install_sh" | grep -q '\\s'; then
  fail "_tracked_skill_names should use [[:space:]] not \\s"
else
  pass "_tracked_skill_names uses portable [[:space:]] regex"
fi

echo ""
echo "=== Test 23: real manifest/lock contain the exact pinned migration set ==="
expected_names=$(printf '%s\n' \
  aoe brainstorming context7 effective-print-design \
  executing-plans find-skills git-commit github-issues graphic-designer impeccable \
  obscura-browser skill-creator systematic-debugging \
  test-driven-development using-superpowers writing-plans | sort)
real_names=$(_tracked_skill_names "$REAL_LOCKFILE")
if [ "$real_names" = "$expected_names" ]; then
  pass "Real lockfile contains exactly the 16 migrated skill names"
else
  fail "Real lockfile skill set differs from the expected migration set"
fi
REAL_MANIFEST="$(dirname "$REAL_LOCKFILE")/apm.yml"
if [ "$(grep -c '^[[:space:]]*ref: [0-9a-f]\{40\}$' "$REAL_MANIFEST")" -eq 16 ]; then
  pass "Manifest pins all 16 dependencies to full commit SHAs"
else
  fail "Manifest must contain 16 full-SHA ref pins"
fi

echo ""
echo "=== ALL TESTS COMPLETE ==="
