# Inventaire des circuits Apex Timing

> Investigation réalisée le 2026-05-26 — connexions WS testées en direct.

---

## Formule port WebSocket

`configPort` se lit dans `https://www.apex-timing.com/live-timing/<slug>/javascript/config.js`

```
WSS port = configPort + 3   ← à utiliser en priorité
WS  port = configPort + 2
```

Source confirmée dans `javascript_live_timing.min.js` :
```js
if("https:"==window.location.protocol)
  var t="wss://"+tzfnj+":"+(tzfos+3)+"/"
else
  t="ws://"+tzfnj+":"+(tzfos+2)+"/"
```

---

## Hôtes WebSocket

Trois hôtes distincts selon le circuit (lu dans `configHost` de `config.js`) :
- `www.apex-timing.com` (51.68.170.219) — majorité des circuits
- `live-data.apex-timing.com` (57.129.51.39) — quelques circuits (ffsa, fiakarting…)
- `live.apex-timing.com` — circuits spéciaux (Spa, kartplanet, onlykart, ckbesancon…)

> ⚠ `configHost` peut être erroné : karting-eupen déclare `live-data` mais répond sur `www`.
> Le client doit tester les deux hôtes en fallback.

> ⚠ `client.py` hardcode `www.apex-timing.com` → circuits sur `live-data` ou `live.` échoueraient si inactifs sur `www`.

---

## Circuits — www.apex-timing.com

| Slug | Nom | URL interface | configHost (config.js) | configPort | WS port | Testé actif |
|------|-----|---------------|------------------------|------------|---------|-------------|
| karting-de-saintes | Karting de Saintes | https://www.apex-timing.com/live-timing/karting-de-saintes/ | live-data.apex-timing.com | 8580 | **8583** | — |
| karting-mariembourg | Karting des Fagnes (Mariembourg) | https://www.apex-timing.com/live-timing/karting-mariembourg/ | www.apex-timing.com | 8310 | **8313** | ✓ |
| karting-genk | Karting de Genk | https://www.apex-timing.com/live-timing/karting-genk/ | www.apex-timing.com | 8240 | **8243** | ✓ |
| karting-eupen | Karting Eupen | https://www.apex-timing.com/live-timing/karting-eupen/ | live-data ⚠ (fonctionne sur www) | 8520 | **8523** | ✓ sur www |
| mrkagadir | MRK Agadir | https://www.apex-timing.com/live-timing/mrkagadir/ | www.apex-timing.com | 8020 | **8023** | — |
| misanino | Misanino | https://www.apex-timing.com/live-timing/misanino/ | — (pas de config.js trouvé) | — | **8043** | — |
| lemans-karting2 | ACO Le Mans Karting 2 | https://www.apex-timing.com/live-timing/lemans-karting2/ | www.apex-timing.com | 8010 | **8013** | ✓ |
| mk-circuit | MK Circuit | https://www.apex-timing.com/live-timing/mk-circuit/ | www.apex-timing.com | 8080 | **8083** | — |
| firstkartinn | First Kart Inn | https://www.apex-timing.com/live-timing/firstkartinn/ | live-data.apex-timing.com | 8110 | **8113** | — |
| lavalloisirskart | Laval Loisirs Kart | https://www.apex-timing.com/live-timing/lavalloisirskart/ | live-data.apex-timing.com | 8120 | **8123** | — |
| worldkarts | WorldKarts | https://www.apex-timing.com/live-timing/worldkarts/ | live-data.apex-timing.com | 8140 | **8143** | — |
| sportkarting | Sport Karting Vallée | https://www.apex-timing.com/live-timing/sportkarting/ | live-data.apex-timing.com | 8160 | **8163** | — |
| circuit-europe | Circuit de l'Europe | https://www.apex-timing.com/live-timing/circuit-europe/ | www.apex-timing.com | 8200 | **8203** | ✓ |
| paris-kart | Paris Kart Indoor | https://www.apex-timing.com/live-timing/paris-kart/ | www.apex-timing.com | 8210 | **8213** | — |
| karting-45 | Karting 45 | https://www.apex-timing.com/live-timing/karting-45/ | www.apex-timing.com | 8370 | **8373** | — |
| circuit-de-lenclos | Circuit de l'Enclos | https://www.apex-timing.com/live-timing/circuit-de-lenclos/ | www.apex-timing.com | 8490 | **8493** | — |
| wik | Wavre Indoor Karting | https://www.apex-timing.com/live-timing/wik/ | live-data.apex-timing.com | 8550 | **8553** | — |
| cornwall-karting | Cornwall Karting | https://www.apex-timing.com/live-timing/cornwall-karting/ | www.apex-timing.com | 8590 | **8593** | ✓ |
| brignoles-karting-loisir | Brignoles Karting Loisirs | https://www.apex-timing.com/live-timing/brignoles-karting-loisir/ | live-data.apex-timing.com | 8600 | **8603** | — |
| fastlane-indoor-racing | Fastlane Indoor Racing | https://www.apex-timing.com/live-timing/fastlane-indoor-racing/ | live-data.apex-timing.com | 8670 | **8673** | — |
| xtremekarting-edinburgh | Xtreme Karting Edinburgh | https://www.apex-timing.com/live-timing/xtremekarting-edinburgh/ | www.apex-timing.com | 8830 | **8833** | — |
| xtremekarting-falkirk | Xtreme Karting Falkirk | https://www.apex-timing.com/live-timing/xtremekarting-falkirk/ | www.apex-timing.com | 8840 | **8843** | — |
| karting-haute-picardie | Karting Haute-Picardie | https://www.apex-timing.com/live-timing/karting-haute-picardie/ | www.apex-timing.com | 9150 | **9153** | — |
| lfkarting | LF Karting | https://www.apex-timing.com/live-timing/lfkarting/ | www.apex-timing.com | 9480 | **9483** | — |
| dutchracingseries | Dutch Racing Series (Lelystad) | https://www.apex-timing.com/live-timing/dutchracingseries/ | www.apex-timing.com | 9460 | **9463** | — |
| capkarting | Circuit de Bresse | https://www.apex-timing.com/live-timing/capkarting/ | www.apex-timing.com | 7950 | **7953** | — |
| kartland | Kartland | https://www.apex-timing.com/live-timing/kartland/ | www.apex-timing.com | 7730 | **7733** | — |
| ouestkarting | Ouest Karting | https://www.apex-timing.com/live-timing/ouestkarting/ | www.apex-timing.com | 7980 | **7983** | — |
| circuitpaulricardkarting | Circuit Paul Ricard Karting | https://www.apex-timing.com/live-timing/circuitpaulricardkarting/ | www.apex-timing.com | 7920 | **7923** | — |
| rkc | Racing Kart Cormeilles | https://www.apex-timing.com/live-timing/rkc/ | www.apex-timing.com | 7910 | **7913** | — |
| larkhall-circuit | Larkhall / WSKC | https://www.apex-timing.com/live-timing/larkhall-circuit/ | www.apex-timing.com | 7320 | **7323** | — |
| ligue-karting-idf | Ligue Karting IDF | https://www.apex-timing.com/live-timing/ligue-karting-idf/ | www.apex-timing.com | 7360 | **7363** | — |
| ffsa-karting | FFSA Karting | https://www.apex-timing.com/live-timing/ffsa-karting/ | live-data.apex-timing.com | 7260 | **7263** | — |
| fiakarting | FIA Karting | https://www.apex-timing.com/live-timing/fiakarting/ | live-data.apex-timing.com | 7810 | **7813** | ✓ sur live-data |
| cik-fia | FIA Karting (ancien slug) | https://www.apex-timing.com/live-timing/cik-fia/ | — | — | — | — |
| wsk | WSK | https://www.apex-timing.com/live-timing/wsk/ | www.apex-timing.com | 7430 | **7433** | — |
| tvkc | TVKC | https://www.apex-timing.com/live-timing/tvkc/ | www.apex-timing.com | 7870 | **7873** | — |
| rgmmc | RGMMC | https://www.apex-timing.com/live-timing/rgmmc/ | — | 7680 | **7683** | — |
| korridas | Korridas | https://www.apex-timing.com/live-timing/korridas/ | — | 7630 | **7633** | — |
| sportstimingsystems2 | Sports Timing Systems 2 | https://www.apex-timing.com/live-timing/sportstimingsystems2/ | — | 7500 | **7503** | — |
| elk-motorsport | ELK Motorsport | https://www.apex-timing.com/live-timing/elk-motorsport/ | — | 8260 | **8263** | — |
| apex | Apex (démo) | https://www.apex-timing.com/live-timing/apex/ | — | 7830 | **7833** | — |

---

## Circuits — live.apex-timing.com

| Slug | Nom | URL interface | configPort | WS port | Testé actif |
|------|-----|---------------|------------|---------|-------------|
| spa-francorchamps-karting | Spa Francorchamps Karting | https://live.apex-timing.com/spa-francorchamps-karting/ | 9720 | **9723** | ✓ |
| onlykart | Onlykart | https://live.apex-timing.com/onlykart/ | 9320 | **9323** | ✓ |
| kartplanet | Kart Planet | https://live.apex-timing.com/kartplanet/ | 10220 | **10223** | ✓ |
| ckbesancon | CKB Besançon | https://live.apex-timing.com/ckbesancon/ | 9640 | **9643** | ✓ |
| karttiming | Apex Kart Timing | https://live.apex-timing.com/karttiming/ | 9580 | **9583** | — |
| wfr | WFR | https://live.apex-timing.com/wfr/ | 7150 | **7153** | — |
| kartodromo-lucas-guerrero | Kartódromo Lucas Guerrero | https://live.apex-timing.com/kartodromo-lucas-guerrero/ | 9950 | **9953** | — |
| cof-us | Champions of the Future America | https://live.apex-timing.com/cof-us/ | 6920 | **6923** | — |
| kln | Karting Loisirs Neuilly | https://live.apex-timing.com/kln/ | 10050 | **10053** | — |
| karting-sevilla | Karting Sevilla | https://live.apex-timing.com/karting-sevilla/ | 9860 | **9863** | — |
| wsk | WSK (live.) | https://live.apex-timing.com/wsk/ | 7430 | **7433** | — |
| lfkarting | LF Karting (live.) | https://live.apex-timing.com/lfkarting/ | 9480 | **9483** | — |
| Worldkarts | WorldKarts (live.) | https://live.apex-timing.com/Worldkarts/ | 8140 | **8143** | — |

---

## Circuits déjà dans l'app (CIRCUIT_PRESETS / KNOWN_CIRCUITS)

Présents dans `backend/app/models.py` et `proxy/app/main.py`. Ports confirmés corrects.

| Slug | URL interface | WS port app | WS port config.js | Hôte correct |
|------|---------------|-------------|-------------------|--------------|
| karting-de-saintes | https://www.apex-timing.com/live-timing/karting-de-saintes/ | 8583 | 8583 | live-data ⚠ (client hardcode www) |
| karting-mariembourg | https://www.apex-timing.com/live-timing/karting-mariembourg/ | 8313 | 8313 | www ✓ |
| karting-genk | https://www.apex-timing.com/live-timing/karting-genk/ | 8243 | 8243 | www ✓ |
| karting-eupen | https://www.apex-timing.com/live-timing/karting-eupen/ | 8523 | 8523 | www ✓ (config.js dit live-data mais www fonctionne) |
| mrkagadir | https://www.apex-timing.com/live-timing/mrkagadir/ | 8023 | 8023 | www ✓ |
| misanino | https://www.apex-timing.com/live-timing/misanino/ | 8043 | — | www (config.js absent) |
| spa-francorchamps-karting | https://live.apex-timing.com/spa-francorchamps-karting/ | 9723 | 9723 | live.apex-timing.com ✓ |

**À ajouter :** `lemans-karting2` → `https://www.apex-timing.com/live-timing/lemans-karting2/`, port **8013**

---

## Todo technique

- `client.py` hardcode `www.apex-timing.com` → doit aussi tenter `live-data.apex-timing.com` et `live.apex-timing.com`
- `port_discovery.py` : lire `configHost` depuis `config.js` en plus de `configPort`
- Enrichir `CIRCUIT_PRESETS` / `KNOWN_CIRCUITS` avec les nouveaux circuits + champ `country` pour groupement par pays (voir backlog)
