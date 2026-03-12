# HA Eau de Marseille

Container Docker standalone qui importe la consommation d'eau (Eau de Marseille Métropole / SEMM) dans Home Assistant, à la manière de [ha-linky](https://github.com/bokub/ha-linky).

## Données importées

| Statistique | Unité | Description |
|-------------|-------|-------------|
| `eaudemarseille:<contrat>` | L | Consommation journalière en litres (cumulative) |
| `eaudemarseille:<contrat>_cost` | € | Coût journalier (si `price_per_m3` configuré) |

Les statistiques sont disponibles dans le dashboard Énergie de HA (section Eau) et dans les graphiques d'historique.

## Prérequis

- Compte espace client : https://espaceclients.eaudemarseille-metropole.fr
- Télérelevé activé
- Token Home Assistant longue durée (Profil > Tokens d'accès longue durée)

## Installation

### 1. Créer la configuration

```bash
mkdir -p ~/ha-eaudemarseille
cp options.json.example ~/ha-eaudemarseille/options.json
# Éditer avec vos identifiants et tarif
```

**options.json** :
```json
{
  "username": "votre_identifiant@email.com",
  "password": "votre_mot_de_passe",
  "price_per_m3": 3.45,
  "name": "Eau de Marseille"
}
```

| Champ | Requis | Description |
|-------|--------|-------------|
| `username` | oui | Identifiant espace client SEMM |
| `password` | oui | Mot de passe |
| `price_per_m3` | non | Prix au m³ en € (pour le calcul du coût) |
| `name` | non | Nom affiché dans HA (défaut: "Eau de Marseille") |
| `action` | non | `sync` (défaut) ou `reset` (supprime les statistiques) |

### 2. Builder l'image Docker

```bash
docker build https://github.com/a-legrand/ha-eaudemarseille.git \
  -f standalone.Dockerfile \
  -t ha-eaudemarseille
```

### 3. Lancer le container

```bash
docker run -d \
  --name ha-eaudemarseille \
  --network container:homeassistant \
  -e SUPERVISOR_TOKEN='VOTRE_TOKEN_LONGUE_DUREE' \
  -e WS_URL='ws://localhost:8123/api/websocket' \
  -e TZ='Europe/Paris' \
  -v ~/ha-eaudemarseille:/data \
  --restart unless-stopped \
  ha-eaudemarseille
```

## Fonctionnement

1. Au démarrage, se connecte à l'API SEMM et à HA via WebSocket
2. Si première exécution : importe jusqu'à 3 ans d'historique journalier
3. Sinon : synchronise les nouvelles données depuis la dernière statistique connue
4. Planifie une synchro automatique 2x/jour (6h et 9h, minute aléatoire)

## API SEMM

L'intégration utilise l'API reverse-engineerée de l'espace client SEMM (SOMEI).

### Authentification (2 étapes)

```
1. POST /webapi/Acces/generateToken → app token
2. POST /webapi/Utilisateur/authentification → user token
```

### Données

```
GET /webapi/Consommation/listeConsommationsInstanceAlerteChart/{contrat}/{startTs}/{endTs}/JOURNEE/true
→ { consommations: [{ dateReleve, volumeConsoEnLitres, volumeConsoEnM3, valeurIndex }] }
```

## Test API

```bash
pip install aiohttp
python3 test_api.py <identifiant> <mot_de_passe>
```
