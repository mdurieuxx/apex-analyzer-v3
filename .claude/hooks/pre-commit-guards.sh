#!/usr/bin/env bash
# Target: .claude/hooks/pre-commit-guards.sh
# Wired as a commit-msg hook via `git config core.hooksPath .claude/hooks`.
# Git only looks for a file literally named `commit-msg` in that directory,
# so `.claude/hooks/commit-msg` is a symlink to this script.
# Enforced, not just documented — see CLAUDE.md "Git & déploiement".
#
# Two independent guards in one hook (this repo is small enough that it
# does not need a hook per rule):
#
#   (a) reject a commit made directly on `main` — main is production here,
#       a push to it triggers CI/CD and deploys to the k3s cluster.
#   (b) reject a commit message that mentions an AI assistant — a commit
#       describes the change, not the tool that wrote it.
#
# receives: $1 = path to the commit message file (standard commit-msg hook)
set -euo pipefail

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"

if [ "$branch" = "main" ]; then
  echo "x Commit rejected: direct commit on \"main\"." >&2
  echo "  main is production -- work on a feature branch instead." >&2
  echo "  git switch -c feat/<subject>" >&2
  exit 1
fi

msg_file="${1:-}"
msg=""
[ -n "$msg_file" ] && [ -f "$msg_file" ] && msg="$(cat "$msg_file")"

# Strip references to the `.claude/` directory itself before matching --
# a line naming a hook or skill path is not an attribution.
checked="$(printf '%s' "$msg" | sed -E 's#\.claude(/[A-Za-z0-9_.-]*)*##g')"

banned='claude|co-authored-by|anthropic|🤖'

if printf '%s' "$checked" | grep -qiE "$banned"; then
  echo "x Commit rejected: the message mentions an AI assistant." >&2
  echo "  A commit describes the change, not the tool that wrote it." >&2
  printf '%s\n' "$msg" | grep -inE "$banned" >&2
  exit 1
fi
