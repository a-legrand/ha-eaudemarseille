"""API client for Eau de Marseille Métropole (SEMM)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    GRANULARITY_DAILY,
    GRANULARITY_MONTHLY,
    URL_AUTH,
    URL_CONSUMPTION,
    URL_CONTRATS,
    URL_GENERATE_TOKEN,
    URL_LAST_READING,
    WS_APPLICATION_LOGIN,
    WS_APPLICATION_PWD,
)

_LOGGER = logging.getLogger(__name__)

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
    """Authentication failed."""


class ApiError(Exception):
    """API call failed."""


@dataclass
class WaterConsumptionData:
    """Water consumption data."""

    contract_number: str | None = None
    contract_holder: str | None = None

    # Daily consumption (last day with data)
    daily_consumption_liters: float | None = None
    daily_date: str | None = None

    # Monthly total (current month)
    monthly_consumption_liters: float | None = None

    # Yearly total
    yearly_consumption_liters: float | None = None

    # Meter index (from last daily entry)
    meter_index_liters: float | None = None

    # Last official reading (from getDerniereConsommationReleveeSem)
    last_reading_index_m3: float | None = None
    last_reading_date: str | None = None
    last_reading_volume_liters: float | None = None
    last_reading_anomaly: str | None = None

    # Daily history (last 30 days)
    daily_history: list[dict[str, Any]] = field(default_factory=list)


class EauMarseilleApiClient:
    """Client for Eau de Marseille Métropole API.

    Authentication flow:
    1. POST /Acces/generateToken  -> app token
    2. POST /Utilisateur/authentification -> tokenAuthentique (user session)
    """

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._conversation_id: str = ""
        self._user_token: str | None = None
        self._contract_id: str | None = None
        self._contract_holder: str | None = None

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

    async def authenticate(self) -> bool:
        """Two-step authentication."""
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

        return True

    def _headers(self) -> dict[str, str]:
        return {
            "ConversationId": self._conversation_id,
            "Token": self._user_token or "",
        }

    async def _get(self, url: str, params: dict | None = None) -> Any:
        """Authenticated GET with auto-reauth on 401."""
        if not self._user_token:
            await self.authenticate()
        session = await self._get_session()

        async with session.get(url, params=params, headers=self._headers()) as resp:
            if resp.status == 401:
                self._user_token = None
                await self.authenticate()
                async with session.get(url, params=params, headers=self._headers()) as r2:
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
            self._contract_holder = first.get("nomClientTitulaire", "")

    async def get_consumption(
        self, start: datetime, end: datetime, granularity: str
    ) -> list[dict]:
        """Fetch consumption data."""
        await self._fetch_contract()
        if not self._contract_id:
            return []
        url = (
            f"{URL_CONSUMPTION}/{self._contract_id}"
            f"/{int(start.timestamp())}/{int(end.timestamp())}"
            f"/{granularity}/true"
        )
        data = await self._get(url)
        if not data:
            return []
        return data.get("consommations", [])

    async def get_last_reading(self) -> dict | None:
        """Fetch last official meter reading."""
        await self._fetch_contract()
        if not self._contract_id:
            return None
        return await self._get(f"{URL_LAST_READING}/{self._contract_id}")

    async def get_data(self) -> WaterConsumptionData:
        """Fetch all water consumption data."""
        result = WaterConsumptionData()

        await self._fetch_contract()
        result.contract_number = self._contract_id
        result.contract_holder = self._contract_holder

        if not self._contract_id:
            return result

        now = datetime.now()

        # Daily: last 30 days
        d30_start = (now - timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        d30_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        daily = await self.get_consumption(d30_start, d30_end, GRANULARITY_DAILY)

        if daily:
            result.daily_history = [
                {
                    "date": e["dateReleve"],
                    "liters": e["volumeConsoEnLitres"],
                    "m3": e["volumeConsoEnM3"],
                    "index": e["valeurIndex"],
                }
                for e in daily
            ]
            last = daily[0]  # API returns most recent first
            result.daily_consumption_liters = last["volumeConsoEnLitres"]
            result.daily_date = last["dateReleve"][:10]
            result.meter_index_liters = last["valeurIndex"]

        # Monthly: current month
        month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        month_daily = await self.get_consumption(month_start, d30_end, GRANULARITY_DAILY)
        if month_daily:
            result.monthly_consumption_liters = sum(
                e["volumeConsoEnLitres"] for e in month_daily
            )

        # Yearly: current year
        year_start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        year_monthly = await self.get_consumption(year_start, d30_end, GRANULARITY_MONTHLY)
        if year_monthly:
            result.yearly_consumption_liters = sum(
                e["volumeConsoEnLitres"] for e in year_monthly
            )

        # Last official reading
        reading = await self.get_last_reading()
        if reading:
            result.last_reading_index_m3 = reading.get("valeurIndex")
            result.last_reading_date = (reading.get("dateReleve") or "")[:10]
            result.last_reading_volume_liters = reading.get("volumeConsoEnLitres")
            result.last_reading_anomaly = reading.get("libelleAnomalieReleve")

        return result
