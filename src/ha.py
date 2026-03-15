"""Home Assistant WebSocket client for importing statistics."""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import websockets

log = logging.getLogger("eaudemarseille")

WS_URL = os.environ.get("WS_URL", "ws://supervisor/core/websocket")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")


class HomeAssistantClient:
    """WebSocket client to push statistics into Home Assistant."""

    def __init__(self) -> None:
        self._ws = None
        self._msg_id = 1

    async def connect(self) -> None:
        """Connect and authenticate to Home Assistant WebSocket API."""
        self._ws = await websockets.connect(WS_URL)

        # Wait for auth_required
        msg = json.loads(await self._ws.recv())
        if msg.get("type") != "auth_required":
            raise ConnectionError(f"Expected auth_required, got: {msg.get('type')}")

        # Send auth
        await self._ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))

        msg = json.loads(await self._ws.recv())
        if msg.get("type") == "auth_invalid":
            raise ConnectionError(
                f"Authentication failed: {msg.get('message', 'invalid token')}"
            )
        if msg.get("type") != "auth_ok":
            raise ConnectionError(f"Expected auth_ok, got: {msg.get('type')}")

        log.info("Connected to Home Assistant")

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _send(self, payload: dict) -> dict:
        """Send a message and wait for the response."""
        payload["id"] = self._msg_id
        self._msg_id += 1
        await self._ws.send(json.dumps(payload))

        # Read messages until we get the response for our id
        while True:
            raw = await self._ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == payload["id"]:
                if not msg.get("success", False):
                    raise RuntimeError(
                        f"HA returned error: {json.dumps(msg.get('error', msg))}"
                    )
                return msg
            # Skip event messages etc.

    @staticmethod
    def _statistic_id(contract_id: str, is_cost: bool = False) -> str:
        suffix = "_cost" if is_cost else ""
        return f"eaudemarseille:{contract_id}{suffix}"

    async def save_statistics(
        self,
        contract_id: str,
        name: str,
        stats: list[dict],
        is_cost: bool = False,
    ) -> None:
        """Import statistics into Home Assistant recorder.

        stats: list of {start: ISO string, state: float, sum: float}
        """
        statistic_id = self._statistic_id(contract_id, is_cost)
        source = statistic_id.split(":")[0]

        await self._send(
            {
                "type": "recorder/import_statistics",
                "metadata": {
                    "has_mean": False,
                    "has_sum": True,
                    "name": f"{name} (coût)" if is_cost else name,
                    "source": source,
                    "statistic_id": statistic_id,
                    "unit_of_measurement": "€" if is_cost else "L",
                },
                "stats": stats,
            }
        )
        log.info(
            "Imported %d %s statistics for %s",
            len(stats),
            "cost" if is_cost else "consumption",
            contract_id,
        )

    async def is_new(self, contract_id: str) -> bool:
        """Check if this contract already has statistics in HA."""
        statistic_id = self._statistic_id(contract_id)
        result = await self._send(
            {"type": "recorder/list_statistic_ids", "statistic_type": "sum"}
        )
        return not any(
            s["statistic_id"] == statistic_id for s in result.get("result", [])
        )

    async def find_last_statistic(
        self, contract_id: str, is_cost: bool = False
    ) -> dict | None:
        """Find the most recent statistic for this contract.

        Returns {start, end, state, sum, change} or None.
        """
        statistic_id = self._statistic_id(contract_id, is_cost)

        # Check existence first
        if await self.is_new(contract_id):
            return None

        now = datetime.now(timezone.utc)
        # Search backwards week by week, up to 3 years
        for i in range(156):
            end_time = now - timedelta(weeks=i)
            start_time = end_time - timedelta(weeks=1)
            result = await self._send(
                {
                    "type": "recorder/statistics_during_period",
                    "start_time": start_time.strftime("%Y-%m-%dT00:00:00+00:00"),
                    "end_time": end_time.strftime("%Y-%m-%dT00:00:00+00:00"),
                    "statistic_ids": [statistic_id],
                    "period": "day",
                }
            )
            points = result.get("result", {}).get(statistic_id, [])
            if points:
                last = points[-1]
                start = last["start"]
                local_tz = ZoneInfo(os.environ.get("TZ", "Europe/Paris"))
                label = start[:10] if isinstance(start, str) else datetime.fromtimestamp(start / 1000, tz=local_tz).strftime("%Y-%m-%d")
                log.info("Last statistic: %s", label)
                return last

        log.warning("No statistics found for %s", contract_id)
        return None

    async def purge(self, contract_id: str) -> None:
        """Delete all statistics for this contract."""
        log.warning("Removing all statistics for contract %s", contract_id)
        await self._send(
            {
                "type": "recorder/clear_statistics",
                "statistic_ids": [
                    self._statistic_id(contract_id, False),
                    self._statistic_id(contract_id, True),
                ],
            }
        )
