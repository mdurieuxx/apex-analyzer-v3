---
name: session-doctor
description: Diagnostic rapide en début de session — claude doctor, statut Remote Control, git status en un coup. Utiliser au début d'une session pour savoir où on en est sans fouiller à la main.
---

# Diagnostic de session — container claude-code-docker

Générique, copié par le fallback (`git-checkout.sh`) si le repo cloné n'a
pas ses propres skills.

```bash
claude doctor 2>&1 | head -40
echo "--- Remote Control ---"
[ -n "$CLAUDE_REMOTE_CONTROL" ] && echo "actif: $CLAUDE_REMOTE_CONTROL" || echo "off"
[ -f /root/.claude/.credentials.json ] && echo ".credentials.json présent" || echo "pas de session Remote Control"
echo "--- git ---"
git -C /workspace status --short 2>/dev/null || echo "/workspace n'est pas un repo git"
```

Un `CLAUDE_REMOTE_CONTROL` actif sans `.credentials.json` (ou avec
`/root/.claude` non monté — voir `git-hygiene` et
`adr/012-remote-control-credentials-persistence.md` du repo
`claude-code-docker`) veut dire que la session Remote Control ne
survivra pas au prochain redémarrage de pod.
