---
name: resume-checkpoint
description: Lit checkpoint-next-prompt.md/PROGRESS.md du repo cloné et en fait un résumé pour reprendre une session sans tout relire à la main. Utiliser en début de session sur un repo qui a déjà ces fichiers.
---

# Reprendre une session — résumé des fichiers de contexte

Générique, copié par le fallback (`git-checkout.sh`) si le repo cloné n'a
pas ses propres skills.

```bash
cd /workspace
[ -f checkpoint-next-prompt.md ] && echo "=== checkpoint-next-prompt.md ===" && cat checkpoint-next-prompt.md
[ -f PROGRESS.md ] && echo "=== PROGRESS.md (dernières entrées) ===" && tail -100 PROGRESS.md
[ -f backlog.md ] && echo "=== backlog.md ===" && cat backlog.md
```

Résumer en quelques lignes plutôt que de tout réafficher : état actuel,
ce qui est en cours, prochaine étape. Si `checkpoint-next-prompt.md`
n'existe pas, ne pas le créer par anticipation — seulement s'il devient
utile de fixer un point de reprise explicite pour la prochaine session.
