"""Constants for the Eau de Marseille Métropole integration."""

DOMAIN = "eau_marseille"

BASE_URL = "https://espaceclients.eaudemarseille-metropole.fr"
API_BASE = f"{BASE_URL}/webapi"

# Application credentials (from app.js AngularJS bundle)
WS_APPLICATION_LOGIN = "SOMEI-SEMM-PRD"
WS_APPLICATION_PWD = "XX_ma3pD-2017-SEMM-PRD!"

# API endpoints
URL_GENERATE_TOKEN = f"{API_BASE}/Acces/generateToken"
URL_AUTH = f"{API_BASE}/Utilisateur/authentification"
URL_CONTRATS = f"{API_BASE}/Abonnement/contrats"
# /Consommation/listeConsommationsInstanceAlerteChart/{contractId}/{startTs}/{endTs}/{granularity}/true
URL_CONSUMPTION = f"{API_BASE}/Consommation/listeConsommationsInstanceAlerteChart"
# /Consommation/getDerniereConsommationReleveeSem/{contractId}
URL_LAST_READING = f"{API_BASE}/Consommation/getDerniereConsommationReleveeSem"

GRANULARITY_DAILY = "JOURNEE"
GRANULARITY_MONTHLY = "MOIS"

DEFAULT_SCAN_INTERVAL = 43200  # 12 hours (2x per day)
