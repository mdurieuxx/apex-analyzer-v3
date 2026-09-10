---
name: git-hygiene
description: Statut du checkpoint automatique du container (dernier autosave, GIT_TASK_BRANCH vs GIT_BASE_BRANCH) et suggestion de cleanup si déjà mergée. Utiliser en début de session, ou quand on demande "où en est le checkpoint", "cette branche est-elle encore utile".
---

# Hygiène git — container claude-code-docker

Générique, copié par le fallback (`git-checkout.sh`) si le repo cloné n'a
pas ses propres skills. Concerne le mécanisme de checkpoint du container
(`git-checkpoint.sh`, adr/006), pas ce projet en particulier.

```bash
BASE="${GIT_BASE_BRANCH:-develop}"
TASK="${GIT_TASK_BRANCH:-feature/auto}"

git status --short                                    # non committé
git log --oneline -1 "origin/$TASK" 2>/dev/null        # dernier checkpoint poussé
git log --oneline "origin/$BASE..origin/$TASK" 2>/dev/null   # avance sur la base
git branch --merged "origin/$BASE" | grep -F "$TASK"   # déjà mergée ?
```

Si la dernière commande sort quelque chose : `$TASK` est déjà mergée dans
`$BASE`, signaler que `git-cleanup.sh` peut la supprimer (local+remote).
**Ne jamais lancer `git-cleanup.sh` seul** — rester une décision humaine
(adr/006). Se contenter de le signaler plutôt que de laisser une branche
mergée traîner indéfiniment sans que personne ne le remarque.
