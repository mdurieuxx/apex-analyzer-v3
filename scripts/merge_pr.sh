#!/usr/bin/env bash
# Target: scripts/merge_pr.sh
# Wraps `gh pr merge` with one check that plain `gh pr merge --delete-branch`
# does not make: deleting a PR's head branch auto-closes any other open PR
# whose base points at it, ready or not. Refuses instead of guessing.
#
# Usage: scripts/merge_pr.sh <PR#> [--delete-branch]
set -euo pipefail

pr="${1:-}"
flag="${2:-}"

if [ -z "$pr" ] || { [ -n "$flag" ] && [ "$flag" != "--delete-branch" ]; }; then
  echo "usage: scripts/merge_pr.sh <PR#> [--delete-branch]" >&2
  exit 2
fi

if [ "$flag" = "--delete-branch" ]; then
  head="$(gh pr view "$pr" --json headRefName --jq '.headRefName')"
  # `gh ... --jq` takes a single expression, no --arg (that is a plain jq
  # flag, not gh's) -- interpolate directly. head is a git branch name,
  # never containing a double quote, so no escaping is at risk here.
  dependents="$(gh pr list --state open --json number,baseRefName \
    --jq "[.[] | select(.baseRefName == \"$head\") | .number] | join(\" \")")"
  if [ -n "$dependents" ]; then
    echo "x   refusing --delete-branch: PR(s) $dependents base off $head" >&2
    echo "    retarget them first, then merge again without --delete-branch:" >&2
    for dep in $dependents; do
      echo "      gh pr edit $dep --base <new-base>" >&2
    done
    exit 1
  fi
  gh pr merge "$pr" --merge --delete-branch
else
  gh pr merge "$pr" --merge
fi

echo "ok  merged #$pr"
