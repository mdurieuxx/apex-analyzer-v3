---
name: checkpoint-status
description: Vérifier l'état du checkpoint automatique de ce container (GIT_TASK_BRANCH, dernier push). Utiliser quand on demande "où en est le checkpoint", "le travail a-t-il été sauvegardé", ou avant de supposer qu'un redémarrage perdrait du travail.
---

# Statut du checkpoint automatique

Générique — copié ici par `git-checkout.sh` car ce repo n'avait pas de
skills. Concerne le mécanisme de checkpoint du container
(`claude-code-docker`, `git-checkpoint.sh`), pas ce projet en particulier.

```bash
git status --short
git log --oneline -1 origin/${GIT_TASK_BRANCH:-feature/auto} 2>/dev/null
```

Le premier montre s'il y a du travail non committé (sera repris au
prochain cycle de checkpoint, jusqu'à `CHECKPOINT_INTERVAL_SECONDS`,
300s par défaut). Le second montre le dernier commit réellement poussé —
c'est ce qui survit si le container meurt maintenant.
