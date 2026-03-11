# Eau de Marseille Métropole (SEMM) - Home Assistant Integration

Intégration custom pour Home Assistant permettant de récupérer les données de consommation d'eau depuis l'espace client SEMM.

## Capteurs

| Capteur | Description | Unité |
|---------|-------------|-------|
| Consommation journalière | Dernière journée avec données (télérelevé) | L |
| Consommation mensuelle | Total du mois en cours | L |
| Consommation annuelle | Total de l'année en cours | L |
| Index compteur | Dernier index télérelevé | L |
| Dernier relevé officiel | Index au dernier relevé officiel | m³ |
| Date dernier relevé | Date du dernier relevé officiel | - |
| État compteur | Anomalie éventuelle | - |

Le capteur "Consommation journalière" expose un attribut `history` avec les 7 derniers jours.

## Prérequis

- Home Assistant 2024.1.0+
- Compte espace client : https://espaceclients.eaudemarseille-metropole.fr
- Télérelevé activé (pour la consommation journalière)

## Installation

### HACS (recommandé)

1. HACS > Intégrations > menu ⋮ > Dépôts personnalisés
2. Ajouter l'URL du dépôt, catégorie "Intégration"
3. Chercher "Eau de Marseille", installer, redémarrer HA

### Manuel

Copier `custom_components/eau_marseille/` dans `config/custom_components/` et redémarrer HA.

## Configuration

Paramètres > Appareils et services > Ajouter une intégration > "Eau de Marseille"

## API

L'intégration utilise l'API reverse-engineerée de l'espace client SEMM (SOMEI).

### Authentification (2 étapes)

```
1. POST /webapi/Acces/generateToken
   Headers: { ConversationId: <uuid>, Token: <app_password> }
   Body: { ConversationId, ClientId, AccessKey }
   → { token, expirationDate }

2. POST /webapi/Utilisateur/authentification
   Headers: { ConversationId: <uuid>, Token: <app_token> }
   Body: { identifiant, motDePasse }
   → { tokenAuthentique, utilisateurInfo }
```

### Endpoints données

```
GET /webapi/Abonnement/contrats?userWebId=&recherche=&tri=NumeroContrat&triDecroissant=false&indexPage=0&nbElements=500
→ { resultats: [{ numeroContrat, nomClientTitulaire, ... }] }

GET /webapi/Consommation/listeConsommationsInstanceAlerteChart/{contractId}/{startTs}/{endTs}/{JOURNEE|SEMAINE|MOIS}/true
→ { consommations: [{ dateReleve, valeurIndex, volumeConsoEnLitres, volumeConsoEnM3 }] }

GET /webapi/Consommation/getDerniereConsommationReleveeSem/{contractId}
→ { dateReleve, valeurIndex, volumeConsoEnLitres, nbJours, moyenne, libelleAnomalieReleve }
```

## Test

```bash
pip install aiohttp
python3 test_api.py <identifiant> <mot_de_passe>
```
