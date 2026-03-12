"""API client for Eau de Marseille Métropole (SEMM)."""

import logging
import uuid
from datetime import datetime, timedelta

import aiohttp

log = logging.getLogger("eaudemarseille")

BASE_URL = "https://espaceclients.eaudemarseille-metropole.fr"
API_BASE = f"{BASE_URL}/webapi"

WS_APPLICATION_LOGIN = "SOMEI-SEMM-PRD"
WS_APPLICATION_PWD = "XX_ma3pD-2017-SEMM-PRD!"

URL_GENERATE_TOKEN = f"{API_BASE}/Acces/generateToken"
URL_AUTH = f"{API_BASE}/Utilisateur/authentification"
URL_CONTRATS = f"{API_BASE}/Abonnement/contrats"
URL_CONSUMPTION = f"{API_BASE}/Consommation/listeConsommationsInstanceAlerteChart"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}


class AuthenticationError(Exception):
    pass


class ApiError(Exception):
    pass


class EauMarseilleClient:
    """Client for Eau de Marseille Métropole API."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._conversation_id: str = ""
        self._user_token: str | None = None
        self._contract_id: str | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=REQUEST_HEADERS,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._user_token = None

    async def authenticate(self) -> None:
        """Two-step authentication: app token then user token."""
        session = await self._get_session()
        self._conversation_id = str(uuid.uuid4())

        # Step 1: app token
        async with session.post(
            URL_GENERATE_TOKEN,
            json={
                "ConversationId": self._conversation_id,
                "ClientId": WS_APPLICATION_LOGIN,
                "AccessKey": WS_APPLICATION_PWD,
            },
            headers={
                "ConversationId": self._conversation_id,
                "Token": WS_APPLICATION_PWD,
            },
        ) as resp:
            if resp.status != 200:
                raise ApiError(f"Token generation failed: {resp.status}")
            app_token = (await resp.json())["token"]

        # Step 2: user auth
        async with session.post(
            URL_AUTH,
            json={"identifiant": self._username, "motDePasse": self._password},
            headers={
                "ConversationId": self._conversation_id,
                "Token": app_token,
            },
        ) as resp:
            if resp.status == 401:
                raise AuthenticationError("Invalid credentials")
            if resp.status != 200:
                raise ApiError(f"Authentication failed: {resp.status}")
            auth_data = await resp.json()
            self._user_token = auth_data["tokenAuthentique"]

        log.info("Authenticated successfully")

    def _headers(self) -> dict[str, str]:
        return {
            "ConversationId": self._conversation_id,
            "Token": self._user_token or "",
        }

    async def _get(self, url: str, params: dict | None = None):
        """Authenticated GET with auto-reauth on 401."""
        if not self._user_token:
            await self.authenticate()
        session = await self._get_session()

        async with session.get(url, params=params, headers=self._headers()) as resp:
            if resp.status == 401:
                self._user_token = None
                await self.authenticate()
                async with session.get(
                    url, params=params, headers=self._headers()
                ) as r2:
                    if r2.status != 200:
                        return None
                    return await r2.json()
            if resp.status != 200:
                return None
            return await resp.json()

    async def _fetch_contract(self) -> None:
        """Fetch first contract number."""
        if self._contract_id:
            return
        data = await self._get(
            URL_CONTRATS,
            params={
                "userWebId": "",
                "recherche": "",
                "tri": "NumeroContrat",
                "triDecroissant": "false",
                "indexPage": "0",
                "nbElements": "500",
            },
        )
        if data and data.get("resultats"):
            first = data["resultats"][0]
            self._contract_id = str(first["numeroContrat"])
            log.info("Contract found: %s", self._contract_id)
        else:
            raise ApiError("No contract found")

    async def get_contract_id(self) -> str:
        """Return the contract ID (fetch if needed)."""
        await self._fetch_contract()
        return self._contract_id

    async def get_daily_consumption(
        self, start: datetime, end: datetime
    ) -> list[dict]:
        """Fetch daily consumption data.

        Returns list of dicts with keys:
          dateReleve, volumeConsoEnLitres, volumeConsoEnM3, valeurIndex
        Sorted oldest first.
        """
        await self._fetch_contract()
        if not self._contract_id:
            return []
        url = (
            f"{URL_CONSUMPTION}/{self._contract_id}"
            f"/{int(start.timestamp())}/{int(end.timestamp())}"
            f"/JOURNEE/true"
        )
        data = await self._get(url)
        if not data:
            return []
        entries = data.get("consommations", [])
        # API returns most recent first, reverse to get oldest first
        entries.reverse()
        return entries
