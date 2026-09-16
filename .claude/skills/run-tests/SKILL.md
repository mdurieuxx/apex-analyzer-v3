---
name: run-tests
description: Détecte le stack du repo cloné (Node, Python, Go, Rust...) et lance sa commande de test standard. Utiliser quand on demande "lance les tests" sur un repo dont on ne connaît pas encore la convention.
---

# Lancer les tests — détection générique du stack

Générique, copié par le fallback (`git-checkout.sh`) si le repo cloné n'a
pas ses propres skills. Un vrai `CLAUDE.md`/skill du projet prime toujours
sur ceci s'il documente sa propre commande de test.

Détecter avant de lancer — ne pas deviner :

```bash
cd /workspace
[ -f package.json ] && echo "Node: $(grep -m1 '"test"' package.json)"
[ -f pyproject.toml ] && echo "Python (pyproject): pytest / poetry run pytest / uv run pytest"
[ -f requirements.txt ] && echo "Python (pip): pytest"
[ -f go.mod ] && echo "Go: go test ./..."
[ -f Cargo.toml ] && echo "Rust: cargo test"
[ -f Gemfile ] && echo "Ruby: bundle exec rspec"
```

Pour Node, vérifier le script `test` réel dans `package.json` avant de
lancer `npm test` — certains repos y mettent autre chose (lint, build...)
ou rien du tout. Si plusieurs marqueurs de stack coexistent (monorepo),
ne pas deviner lequel tester : demander, ou tester chaque sous-projet
séparément.
