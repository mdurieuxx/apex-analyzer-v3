# CLAUDE.md — fallback minimal (claude-code-docker)

Ce fichier n'existait pas à la racine du repo cloné — copié ici par
`git-checkout.sh` comme filet générique, pas un remplacement d'un vrai
`CLAUDE.md` projet. Si ce repo en écrit un plus tard, le sien prime.

## Garde-fous

- Ne jamais utiliser `--force`/`--no-verify` (git) ou équivalent sans
  demande explicite de l'utilisateur.
- Ne jamais commit directement sur une branche de production
  (`main`/`master`/`develop` selon le repo) — toujours via une branche
  dédiée.
- Ce container checkpoint et pousse automatiquement le travail non
  committé sur `GIT_TASK_BRANCH` (voir `git-checkpoint.sh`, toutes les
  `CHECKPOINT_INTERVAL_SECONDS` secondes) — committer normalement au fil
  du travail plutôt que de compter dessus comme seul filet.
