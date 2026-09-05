---
name: checkpoint
description: Write a session checkpoint before clearing context, and decide when clearing is the right move. Use it when the context window is filling up, when the subject changes and the current context stops being relevant, or before ending a work session.
---

# Session checkpoint

A checkpoint is a **handover**, not an archive. It answers one question:
what does the next session need in order to pick this up cold?

For this repo it lives in a single file at the repo root:
`checkpoint-next-prompt.md`. One file, this project only — never mix
content from another repo into it, even in a session that touched both
(see the workspace-level CLAUDE.md, "Fichier next prompt").

## The rule that cannot be broken

**Never clear before the checkpoint is committed.** A cleared context is
unrecoverable; an uncommitted checkpoint file lives only in the working
tree and is lost the same way. Commit it on the current feature branch
before ending the session — it never goes on `main` directly, same as any
other change here.

## What to write

Keep it short, three sections:

1. **Where this stands** — one paragraph, present tense: what changed this
   session, what state the branch/PR is in.
2. **Next step** — the single next action, concrete enough to start on
   without re-deriving it.
3. **Traps** — what nearly went wrong, and what a cold reader would get
   wrong (a WS protocol quirk, a fixture that looked wrong but wasn't,
   anything non-obvious hit this session).

Prefer deriving over typing: `git status`, `git log --oneline -5`, and
`git branch --show-current` already answer "what changed" and "what
branch" — don't retype what a command can show.

## The exit rule

The file is **replaced, never appended to**. Its history lives in git,
which is what git is for — a checkpoint file that only ever grows becomes
as expensive to read as the context it was meant to save.

## Resuming a session

Read `checkpoint-next-prompt.md` at the repo root and pick up from there.
If it disagrees with what you observe (branch, working tree, open PRs),
trust the observed state and treat the file's narrative as stale.

## One checkpoint per project, never shared

A checkpoint holds the context of the repository it sits in. Never mix two
repos in one file, even when a session worked on both in a row — each repo
keeps its own `checkpoint-next-prompt.md` at its own root.

## When to clear

Signals that it's time:

- **The subject changed** and the loaded context no longer relates to it.
  The strongest signal, and the most often missed.
- The context window is filling and the remaining work is a fresh start
  rather than a continuation.
- A long exploration ended in a decision: keep the decision, drop the
  exploration.

Counter-signal: a task in flight with unwritten state in the conversation.
Checkpoint first, then decide.
