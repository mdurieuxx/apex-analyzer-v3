# Nginx Proxy Manager — Configuration

## Vue d'ensemble

| Domaine | Upstream | Instance |
|---|---|---|
| `apex-analyzer.durdur.eu` | `192.168.69.253:80` (Traefik k3s) | k3s |
| `apex-proxy.durdur.eu` | `192.168.69.253:80` (Traefik k3s) | k3s |
| `apex-analyzer-2.durdur.eu` | `192.168.69.170:6970` (Synology) | Synology |
| `apex-proxy-2.durdur.eu` | `192.168.69.170:6969` (Synology) | Synology |

---

## apex-analyzer.durdur.eu (k3s)

| Champ | Valeur |
|---|---|
| Domain Names | `apex-analyzer.durdur.eu` |
| Scheme | `http` |
| Forward Hostname / IP | `192.168.69.253` |
| Forward Port | `80` |
| Cache Assets | off |
| Block Common Exploits | on |
| Websockets Support | **on** |
| SSL Certificate | Let's Encrypt |
| Force SSL | on |
| HTTP/2 Support | on |
| HSTS Enabled | on |
| HSTS Subdomains | off |

---

## apex-proxy.durdur.eu (k3s)

| Champ | Valeur |
|---|---|
| Domain Names | `apex-proxy.durdur.eu` |
| Scheme | `http` |
| Forward Hostname / IP | `192.168.69.253` |
| Forward Port | `80` |
| Cache Assets | off |
| Block Common Exploits | on |
| Websockets Support | **on** |
| SSL Certificate | Let's Encrypt |
| Force SSL | on |
| HTTP/2 Support | on |
| HSTS Enabled | on |
| HSTS Subdomains | off |

---

## apex-analyzer-2.durdur.eu (Synology)

| Champ | Valeur |
|---|---|
| Domain Names | `apex-analyzer-2.durdur.eu` |
| Scheme | `http` |
| Forward Hostname / IP | `192.168.69.170` |
| Forward Port | `6970` |
| Cache Assets | off |
| Block Common Exploits | on |
| Websockets Support | **on** |
| SSL Certificate | Let's Encrypt |
| Force SSL | on |
| HTTP/2 Support | on |
| HSTS Enabled | on |
| HSTS Subdomains | off |

---

## apex-proxy-2.durdur.eu (Synology)

| Champ | Valeur |
|---|---|
| Domain Names | `apex-proxy-2.durdur.eu` |
| Scheme | `http` |
| Forward Hostname / IP | `192.168.69.170` |
| Forward Port | `6969` |
| Cache Assets | off |
| Block Common Exploits | on |
| Websockets Support | **on** |
| SSL Certificate | Let's Encrypt |
| Force SSL | on |
| HTTP/2 Support | on |
| HSTS Enabled | on |
| HSTS Subdomains | off |
