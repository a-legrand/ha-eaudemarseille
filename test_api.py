#!/usr/bin/env python3
"""
Test script for Eau de Marseille Métropole API.

Usage:
    python3 test_api.py <identifiant> <mot_de_passe>
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta

import aiohttp
from yarl import URL

BASE_URL = "https://espaceclients.eaudemarseille-metropole.fr"
API_BASE = f"{BASE_URL}/webapi"

WS_APPLICATION_LOGIN = "SOMEI-SEMM-PRD"
WS_APPLICATION_PWD = "XX_ma3pD-2017-SEMM-PRD!"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}


async def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python3 test_api.py <identifiant> <mot_de_passe>")
        sys.exit(1)

    username, password = sys.argv[1], sys.argv[2]
    cid = str(uuid.uuid4())
    print(f"User: {username}")

    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(headers=HEADERS, cookie_jar=jar) as s:

        # Load main page
        async with s.get(BASE_URL) as r:
            print(f"Main page: {r.status}")

        # Step 1: App token
        print("\n--- App token ---")
        async with s.post(
            f"{API_BASE}/Acces/generateToken",
            json={"ConversationId": cid, "ClientId": WS_APPLICATION_LOGIN, "AccessKey": WS_APPLICATION_PWD},
            headers={"ConversationId": cid, "Token": WS_APPLICATION_PWD},
        ) as r:
            data = await r.json()
            app_token = data["token"]
            print(f"  Token: {app_token} (expires {data['expirationDate']})")

        # Step 2: User auth
        print("\n--- User auth ---")
        async with s.post(
            f"{API_BASE}/Utilisateur/authentification",
            json={"identifiant": username, "motDePasse": password},
            headers={"ConversationId": cid, "Token": app_token},
        ) as r:
            auth = await r.json()
            user_token = auth["tokenAuthentique"]
            info = auth["utilisateurInfo"]
            print(f"  {info['prenom']} {info['nom']} - token: {user_token}")

        h = {"ConversationId": cid, "Token": user_token}

        # Step 3: Contracts
        print("\n--- Contracts ---")
        async with s.get(
            f"{API_BASE}/Abonnement/contrats",
            params={"userWebId": "", "recherche": "", "tri": "NumeroContrat",
                    "triDecroissant": "false", "indexPage": "0", "nbElements": "500"},
            headers=h,
        ) as r:
            contracts = await r.json()
            for c in contracts.get("resultats", []):
                print(f"  Contract {c['numeroContrat']}: {c.get('nomClientTitulaire', '')}")
            contract_id = contracts["resultats"][0]["numeroContrat"]

        # Step 4: Daily consumption (last 30 days)
        now = datetime.now()
        d30 = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)

        print(f"\n--- Daily consumption (30 days) - contract {contract_id} ---")
        url = f"{API_BASE}/Consommation/listeConsommationsInstanceAlerteChart/{contract_id}/{int(d30.timestamp())}/{int(end.timestamp())}/JOURNEE/true"
        async with s.get(url, headers=h) as r:
            data = await r.json()
            print(f"  {data['nbTotalConsos']} entries")
            for e in data["consommations"][:5]:
                print(f"  {e['dateReleve'][:10]}  {e['volumeConsoEnLitres']:>5}L  ({e['volumeConsoEnM3']:.3f} m3)  index={e['valeurIndex']}")
            if len(data["consommations"]) > 5:
                print(f"  ... and {len(data['consommations']) - 5} more")

        # Step 5: Monthly consumption (current year)
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        print(f"\n--- Monthly consumption (year) ---")
        url = f"{API_BASE}/Consommation/listeConsommationsInstanceAlerteChart/{contract_id}/{int(year_start.timestamp())}/{int(end.timestamp())}/MOIS/true"
        async with s.get(url, headers=h) as r:
            data = await r.json()
            total = sum(e["volumeConsoEnLitres"] for e in data["consommations"])
            for e in data["consommations"]:
                print(f"  {e['dateReleve'][:7]}  {e['volumeConsoEnLitres']:>6}L  ({e['volumeConsoEnM3']:.3f} m3)")
            print(f"  TOTAL: {total}L ({total/1000:.3f} m3)")

        # Step 6: Last official reading
        print(f"\n--- Last official reading ---")
        async with s.get(f"{API_BASE}/Consommation/getDerniereConsommationReleveeSem/{contract_id}", headers=h) as r:
            data = await r.json()
            print(f"  Date: {data['dateReleve'][:10]}")
            print(f"  Index: {data['valeurIndex']} m3")
            print(f"  Volume: {data['volumeConsoEnLitres']}L over {data['nbJours']} days")
            print(f"  Average: {data['moyenne']:.2f} m3/day")
            print(f"  Status: {data['libelleAnomalieReleve']}")

    print("\n--- DONE ---")


if __name__ == "__main__":
    asyncio.run(main())
