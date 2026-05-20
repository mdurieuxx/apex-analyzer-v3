# CI/CD & k8s Setup — apex-analyzer-v3

Ce document décrit l'infrastructure nécessaire pour reproduire le flux complet :

```
git push main → GitHub Actions (ARC runner sur k3s) → docker build → push registry.k3s → kubectl rollout → pods mis à jour
```

Pensé pour être automatisé via Ansible.

---

## Vue d'ensemble

```
GitHub
  └── Actions workflow (.github/workflows/build-deploy.yml)
        └── Runner ARC (pod k8s dans namespace arc-runners)
              ├── docker build backend + frontend (DinD)
              ├── docker push → registry.k3s (registre local)
              └── kubectl rollout restart → namespace karting-live

k3s cluster (3 nœuds)
  ├── namespace: arc-runners   → ARC controller + runner pods
  ├── namespace: arc-system    → ARC controller (helm release)
  ├── namespace: registry      → registry:2 Docker local
  └── namespace: karting-live  → backend + frontend pods
```

---

## Prérequis

- k3s installé sur 1+ nœuds (testé avec 3 nœuds, dont `durdur-nuc-1` comme nœud principal)
- Helm 3 disponible
- `kubectl` configuré avec kubeconfig du cluster
- GitHub account + token PAT avec scope `repo` (pour ARC)
- DNS interne résolvant `registry.k3s` → ClusterIP du service registry (ou hostAliases)

---

## Étape 1 — Namespaces

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: karting-live
```

```bash
kubectl apply -f k8s/namespace.yaml
kubectl create namespace arc-system
kubectl create namespace arc-runners
kubectl create namespace registry
```

**Ansible** :
```yaml
- name: Create namespaces
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: "{{ item }}"
  loop: [karting-live, arc-system, arc-runners, registry]
```

---

## Étape 2 — Registre Docker local

Déploie `registry:2` dans le namespace `registry`, exposé via Traefik sur `registry.k3s` (HTTP uniquement, pas HTTPS).

```bash
kubectl apply -f k8s/registry/registry.yaml
```

Le manifest crée :
- `Deployment` : image `registry:2`, stockage sur `hostPath /var/lib/registry` (nœud `durdur-nuc-1`)
- `Service` : port 80 → 5000
- `Ingress` : host `registry.k3s`, entrypoint `web` (HTTP), annotation `traefik.ingress.kubernetes.io/router.tls: "false"`

**ClusterIP du service registry** (à noter pour la suite) :
```bash
kubectl get svc registry -n registry -o jsonpath='{.spec.clusterIP}'
# ex: 10.43.156.151
```

---

## Étape 3 — containerd hosts.toml sur tous les nœuds

Nécessaire pour que les pods k8s puissent puller depuis `registry.k3s:80` en HTTP.

Sur **chaque nœud** du cluster :

```bash
mkdir -p /var/lib/rancher/k3s/agent/etc/containerd/certs.d/registry.k3s:80
cat > /var/lib/rancher/k3s/agent/etc/containerd/certs.d/registry.k3s:80/hosts.toml << 'EOF'
server = "http://registry.k3s"
capabilities = ["pull", "resolve", "push"]

[host."http://registry.k3s"]
  capabilities = ["pull", "resolve", "push"]
EOF
```

Redémarrer k3s sur chaque nœud :
```bash
systemctl restart k3s        # nœud principal
systemctl restart k3s-agent  # nœuds workers
```

**Ansible** :
```yaml
- name: Configure containerd registry mirror
  hosts: k3s_nodes
  tasks:
    - name: Create registry cert dir
      file:
        path: /var/lib/rancher/k3s/agent/etc/containerd/certs.d/registry.k3s:80
        state: directory

    - name: Write hosts.toml
      copy:
        content: |
          server = "http://registry.k3s"
          capabilities = ["pull", "resolve", "push"]

          [host."http://registry.k3s"]
            capabilities = ["pull", "resolve", "push"]
        dest: /var/lib/rancher/k3s/agent/etc/containerd/certs.d/registry.k3s:80/hosts.toml

    - name: Restart k3s
      systemd:
        name: "{{ 'k3s' if inventory_hostname == primary_node else 'k3s-agent' }}"
        state: restarted
```

---

## Étape 4 — ARC (Actions Runner Controller)

ARC permet à GitHub Actions d'utiliser des runners hébergés sur le cluster k3s.

### 4.1 Installer le controller

```bash
helm upgrade --install arc \
  --namespace arc-system \
  --create-namespace \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller \
  --version 0.14.1
```

### 4.2 Installer le runner scale set

Le fichier `k8s/arc/runner-values.yaml` configure un DinD (Docker-in-Docker) runner.

**Points critiques** :
- `containerMode` : **ne pas le définir** quand on personnalise le template manuellement
- `command: ["/home/runner/run.sh"]` : obligatoire sur le container runner (l'image a CMD `/bin/bash`)
- `hostAliases` : route `registry.k3s` → ClusterIP du registry (contourne Traefik HTTPS)
- `--insecure-registry=registry.k3s` : dans les args dockerd
- `--group=123` dans dockerd : GID matching pour le socket Docker
- `dnsConfig.nameservers` : CoreDNS ClusterIP pour résoudre les services cluster

```bash
# Récupérer le ClusterIP du registry
REGISTRY_IP=$(kubectl get svc registry -n registry -o jsonpath='{.spec.clusterIP}')

# Mettre à jour le hostAlias dans runner-values.yaml si nécessaire
# Puis déployer :
helm upgrade --install arc-runner-set \
  --namespace arc-runners \
  --create-namespace \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.14.1 \
  -f k8s/arc/runner-values.yaml \
  --set githubConfigSecret.github_token=<GITHUB_PAT>
```

**Ansible** (avec secret dans vault) :
```yaml
- name: Install ARC runner scale set
  command: >
    helm upgrade --install arc-runner-set
    --namespace arc-runners
    --create-namespace
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
    --version 0.14.1
    -f k8s/arc/runner-values.yaml
    --set githubConfigSecret.github_token={{ github_pat }}
  environment:
    KUBECONFIG: /etc/rancher/k3s/k3s.yaml
```

### 4.3 Contenu de runner-values.yaml

```yaml
githubConfigUrl: "https://github.com/<owner>/<repo>"
githubConfigSecret:
  github_token: ""  # injecté via --set

minRunners: 0
maxRunners: 3

template:
  spec:
    dnsConfig:
      nameservers:
        - 10.43.0.10   # CoreDNS ClusterIP (kubectl get svc kube-dns -n kube-system)
    hostAliases:
      - ip: "10.43.156.151"   # ClusterIP du service registry
        hostnames:
          - "registry.k3s"
    initContainers:
      - name: init-dind-externals
        image: ghcr.io/actions/actions-runner:latest
        command: ["cp", "-r", "/home/runner/externals/.", "/home/runner/tmpDir/"]
        volumeMounts:
          - name: dind-externals
            mountPath: /home/runner/tmpDir
      - name: dind
        image: docker:dind
        restartPolicy: Always         # sidecar init container (k8s 1.29+)
        securityContext:
          privileged: true
        args:
          - dockerd
          - --host=unix:///var/run/docker.sock
          - --group=123
          - --insecure-registry=registry.k3s
        startupProbe:
          exec:
            command: [docker, info]
          failureThreshold: 24
          periodSeconds: 5
        volumeMounts:
          - name: work
            mountPath: /home/runner/_work
          - name: dind-sock
            mountPath: /var/run
          - name: dind-externals
            mountPath: /home/runner/externals
    containers:
      - name: runner
        image: ghcr.io/actions/actions-runner:latest
        command: ["/home/runner/run.sh"]   # OBLIGATOIRE — l'image a CMD /bin/bash
        env:
          - name: DOCKER_HOST
            value: unix:///var/run/docker.sock
          - name: RUNNER_WAIT_FOR_DOCKER_IN_SECONDS
            value: "120"
        volumeMounts:
          - name: work
            mountPath: /home/runner/_work
          - name: dind-sock
            mountPath: /var/run
    volumes:
      - name: work
        emptyDir: {}
      - name: dind-sock
        emptyDir: {}
      - name: dind-externals
        emptyDir: {}
```

---

## Étape 5 — RBAC pour kubectl dans les runners

Le runner doit pouvoir faire `kubectl rollout restart` sur le namespace `karting-live`.

ServiceAccount automatiquement créé par ARC : `arc-runner-set-gha-rs-no-permission`

```bash
kubectl apply -f k8s/arc/rbac.yaml
```

```yaml
# k8s/arc/rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: runner-deploy
  namespace: karting-live
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: runner-deploy
  namespace: karting-live
subjects:
  - kind: ServiceAccount
    name: arc-runner-set-gha-rs-no-permission
    namespace: arc-runners
roleRef:
  kind: Role
  name: runner-deploy
  apiGroup: rbac.authorization.k8s.io
```

> **Trouver le vrai nom du ServiceAccount** si différent :
> ```bash
> kubectl get sa -n arc-runners
> ```

---

## Étape 6 — Déploiements applicatifs

```bash
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml
kubectl apply -f k8s/ingress.yaml
```

Les images référencent `registry.k3s:80/apex-analyzer-backend:latest` et `registry.k3s:80/apex-analyzer-frontend:latest`.

`imagePullPolicy: Always` — le pod re-pull à chaque restart.

**Stockage backend** : `hostPath /var/lib/karting-live/data` sur le nœud `durdur-nuc-1` (SQLite + données persistantes). Créer le répertoire si besoin :
```bash
ssh user@durdur-nuc-1 "sudo mkdir -p /var/lib/karting-live/data"
```

---

## Étape 7 — Ingress Traefik

```bash
kubectl apply -f k8s/ingress.yaml
```

Expose :
- `apex-analyzer.k3s` → frontend (DNS interne)
- `apex-analyzer.durdur.eu` → frontend (DNS externe)

Les deux sans TLS (HTTP uniquement, terminé par un reverse proxy externe si besoin).

---

## Étape 8 — Workflow GitHub Actions

Fichier `.github/workflows/build-deploy.yml`. Déclenché sur push sur `main` (paths : `backend/**`, `frontend/**`, `k8s/**`) ou `workflow_dispatch`.

```yaml
name: Build & Deploy
on:
  push:
    branches: [main]
    paths: ["backend/**", "frontend/**", "k8s/**"]
  workflow_dispatch:

jobs:
  build-deploy:
    runs-on: arc-runner-set     # nom du helm release du runner scale set
    steps:
      - uses: actions/checkout@v4

      - name: Build backend
        run: docker build --platform linux/amd64 -t registry.k3s/apex-analyzer-backend:latest ./backend

      - name: Build frontend
        run: docker build --platform linux/amd64 -t registry.k3s/apex-analyzer-frontend:latest ./frontend

      - name: Push images
        run: |
          docker push registry.k3s/apex-analyzer-backend:latest
          docker push registry.k3s/apex-analyzer-frontend:latest

      - name: Install kubectl
        run: |
          curl -LO "https://dl.k8s.io/release/v1.30.0/bin/linux/amd64/kubectl"
          chmod +x kubectl && sudo mv kubectl /usr/local/bin/

      - name: Rollout restart
        run: |
          kubectl rollout restart deployment/backend -n karting-live
          kubectl rollout restart deployment/frontend -n karting-live
          kubectl rollout status deployment/backend -n karting-live --timeout=120s
          kubectl rollout status deployment/frontend -n karting-live --timeout=120s
```

> `kubectl` utilise le kubeconfig injecté automatiquement par ARC via le ServiceAccount du pod runner.

---

## Diagnostic — Problèmes connus et solutions

### Runner sort immédiatement (exit 0)

**Cause** : `containerMode.type: dind` défini en même temps qu'un template custom → ARC n'injecte pas `command: ["/home/runner/run.sh"]`, le container exécute `CMD /bin/bash` et sort.

**Solution** : ne pas définir `containerMode`, écrire le template complet manuellement avec `command: ["/home/runner/run.sh"]` explicite.

### `docker push` échoue avec HTTPS 404

**Cause** : Docker tente HTTPS par défaut. Traefik intercepte sur le port 443 avec son cert self-signed et retourne 404 (valide HTTP, pas TLS error) → Docker ne bascule pas en HTTP.

**Solution** : `hostAliases` route `registry.k3s` directement vers le ClusterIP du service registry. Pas de port 443 sur le ClusterIP → TCP refusé → Docker tombe en HTTP via `--insecure-registry`.

### `kubectl rollout status` : forbidden

**Cause** : le ServiceAccount ARC n'a que `get/patch/update` mais `rollout status` nécessite `list` et `watch`.

**Solution** : ajouter `list` et `watch` dans le Role.

### Backend CrashLoopBackOff après push

**Cause** : fichiers Python non commités (gitignore ou oubli) → image buildée sans les modules → `ModuleNotFoundError` au démarrage.

**Solution** : vérifier `git status` avant push, s'assurer que tous les fichiers `.py` sont trackés.

### DinD init container crash loop

**Cause** : `DOCKER_TLS_CERTDIR: ""` désactive TLS → dockerd écoute uniquement sur socket Unix, pas TCP:2376. Si `DOCKER_HOST=tcp://localhost:2376` → connexion impossible.

**Solution** : ne pas définir `DOCKER_TLS_CERTDIR`. Utiliser `unix:///var/run/docker.sock` via volume partagé `dind-sock`.

---

## Playbook Ansible — Structure recommandée

```
ansible/
├── inventory/
│   ├── hosts.yml           # nœuds k3s
│   └── group_vars/
│       ├── all.yml         # variables communes
│       └── k3s_nodes.yml   # variables nœuds
├── vault/
│   └── secrets.yml         # github_pat (ansible-vault)
├── roles/
│   ├── k3s-containerd-registry/   # étape 3
│   ├── arc-controller/            # étape 4.1
│   ├── arc-runner-set/            # étape 4.2 + 4.3
│   ├── k8s-namespaces/            # étape 1
│   ├── k8s-registry/              # étape 2
│   ├── k8s-rbac/                  # étape 5
│   └── k8s-app/                   # étapes 6 + 7
└── site.yml                # playbook principal
```

```yaml
# site.yml
- hosts: k3s_primary
  roles:
    - k8s-namespaces
    - k8s-registry
    - arc-controller
    - arc-runner-set
    - k8s-rbac
    - k8s-app

- hosts: k3s_nodes
  roles:
    - k3s-containerd-registry
```

### Variables clés (group_vars/all.yml)

```yaml
github_repo: "https://github.com/<owner>/<repo>"
arc_version: "0.14.1"
registry_clusterip: ""          # à remplir après déploiement registry
coredns_clusterip: "10.43.0.10" # kubectl get svc kube-dns -n kube-system
app_node: "durdur-nuc-1"        # nœud hébergeant les hostPath volumes
app_data_path: "/var/lib/karting-live/data"
```

### Secret (vault)

```yaml
# ansible/vault/secrets.yml (chiffré avec ansible-vault)
github_pat: "ghp_xxxxxxxxxxxx"
```

---

## Ordre d'exécution complet

```
1. k3s installé (hors scope Ansible ici)
2. ansible-playbook site.yml --ask-vault-pass
   → namespaces créés
   → registry déployé
   → containerd configuré sur tous les nœuds
   → ARC controller installé (helm)
   → ARC runner scale set installé (helm + PAT)
   → RBAC appliqué
   → déploiements backend/frontend appliqués
   → ingress appliqué
3. Premier push sur main → CI/CD déclenché → images buildées + déployées
```

---

## Vérifications post-installation

```bash
# Runners actifs
kubectl get pods -n arc-runners

# Registry accessible
curl http://registry.k3s/v2/_catalog

# App en ligne
kubectl get pods -n karting-live
curl http://apex-analyzer.k3s/api/status

# Workflow GitHub Actions
gh run list --repo <owner>/<repo> --limit 5
```
