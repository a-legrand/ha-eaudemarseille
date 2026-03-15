"""HA Eau de Marseille - Standalone water consumption tracker for Home Assistant."""

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_config
from api import EauMarseilleClient
from ha import HomeAssistantClient

LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Europe/Paris"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m %H:%M",
)
log = logging.getLogger("eaudemarseille")


def build_statistics(
    daily_data: list[dict], price_per_m3: float | None = None
) -> tuple[list[dict], list[dict]]:
    """Convert daily API data to HA statistics format.

    daily_data: list of API entries sorted oldest first, with keys:
        dateReleve, volumeConsoEnLitres, volumeConsoEnM3

    Returns (consumption_stats, cost_stats).
    Each stat: {start: ISO string, state: float, sum: float}
    """
    consumption_stats = []
    cost_stats = []
    consumption_sum = 0.0
    cost_sum = 0.0

    for entry in daily_data:
        if "volumeConsoEnLitres" not in entry or "volumeConsoEnM3" not in entry:
            log.debug("Skipping entry without consumption data: %s", entry.get("dateReleve", "?"))
            continue
        date_str = entry["dateReleve"][:10]  # "YYYY-MM-DD"
        liters = float(entry["volumeConsoEnLitres"])
        m3 = float(entry["volumeConsoEnM3"])

        # Start of day in local timezone
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        start = dt.isoformat()

        consumption_sum += liters
        consumption_stats.append(
            {"start": start, "state": liters, "sum": consumption_sum}
        )

        if price_per_m3 is not None:
            day_cost = m3 * price_per_m3
            cost_sum += day_cost
            cost_stats.append({"start": start, "state": day_cost, "sum": cost_sum})

    return consumption_stats, cost_stats


def increment_sums(stats: list[dict], base_sum: float) -> list[dict]:
    """Add base_sum to all sum values (for incremental sync)."""
    return [
        {"start": s["start"], "state": s["state"], "sum": s["sum"] + base_sum}
        for s in stats
    ]


async def init(
    config: dict,
    api: EauMarseilleClient,
    ha: HomeAssistantClient,
    contract_id: str,
) -> None:
    """First run: import historical data (up to 3 years)."""
    log.info("New contract detected, importing historical data...")

    now = datetime.now()
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)

    # Fetch up to 3 years of daily data in yearly chunks
    all_data = []
    for years_back in range(3, 0, -1):
        start = (now - timedelta(days=365 * years_back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        chunk_end = (now - timedelta(days=365 * (years_back - 1))).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        if years_back == 1:
            chunk_end = end

        try:
            data = await api.get_daily_consumption(start, chunk_end)
            if data:
                all_data.extend(data)
                log.info("  Fetched %d days (%d-%d)", len(data), years_back, years_back - 1)
        except Exception as e:
            log.warning("  Failed to fetch year -%d: %s", years_back, e)

    if not all_data:
        log.warning("No historical data found")
        return

    # Deduplicate by date (keep last occurrence)
    seen = {}
    for entry in all_data:
        seen[entry["dateReleve"][:10]] = entry
    all_data = [seen[k] for k in sorted(seen.keys())]

    log.info("Total: %d days of historical data", len(all_data))

    consumption_stats, cost_stats = build_statistics(
        all_data, config["price_per_m3"]
    )

    await ha.save_statistics(contract_id, config["name"], consumption_stats)

    if cost_stats:
        await ha.save_statistics(
            contract_id, config["name"], cost_stats, is_cost=True
        )


async def sync(
    config: dict,
    api: EauMarseilleClient,
    ha: HomeAssistantClient,
    contract_id: str,
) -> None:
    """Incremental sync: fetch new data since last known statistic."""
    log.info("Synchronization started")

    last_stat = await ha.find_last_statistic(contract_id)
    if not last_stat:
        log.warning("No previous statistic found, running init instead")
        await init(config, api, ha, contract_id)
        return

    # Parse last stat date
    raw_start = last_stat["start"]
    if isinstance(raw_start, str):
        last_date_str = raw_start[:10]
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
    else:
        last_date = datetime.fromtimestamp(raw_start / 1000, tz=LOCAL_TZ).replace(tzinfo=None)
        last_date_str = last_date.strftime("%Y-%m-%d")

    now = datetime.now()
    # Only sync if last data is at least 2 days old and it's past 6am
    days_behind = (now - last_date).days
    if days_behind < 2 or now.hour < 6:
        log.info("Up to date (last: %s), nothing to sync", last_date_str)
        return

    # Fetch from day after last known
    start = (last_date + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)

    data = await api.get_daily_consumption(start, end)
    if not data:
        log.info("No new data available")
        return

    log.info("Fetched %d new days", len(data))

    consumption_stats, cost_stats = build_statistics(data, config["price_per_m3"])

    # Increment sums from previous cumulative total
    consumption_stats = increment_sums(consumption_stats, last_stat["sum"])
    await ha.save_statistics(contract_id, config["name"], consumption_stats)

    if cost_stats:
        last_cost_stat = await ha.find_last_statistic(contract_id, is_cost=True)
        base_cost_sum = last_cost_stat["sum"] if last_cost_stat else 0
        cost_stats = increment_sums(cost_stats, base_cost_sum)
        await ha.save_statistics(
            contract_id, config["name"], cost_stats, is_cost=True
        )


async def run_sync(config: dict) -> None:
    """Connect, sync, disconnect."""
    api = EauMarseilleClient(config["username"], config["password"])
    ha = HomeAssistantClient()

    try:
        await ha.connect()
        contract_id = await api.get_contract_id()

        is_new = await ha.is_new(contract_id)
        if is_new:
            await init(config, api, ha, contract_id)
        else:
            await sync(config, api, ha, contract_id)
    finally:
        await ha.disconnect()
        await api.close()


async def main() -> None:
    log.info("HA Eau de Marseille starting")

    config = get_config()

    if config["action"] == "reset":
        api = EauMarseilleClient(config["username"], config["password"])
        ha = HomeAssistantClient()
        try:
            await ha.connect()
            contract_id = await api.get_contract_id()
            await ha.purge(contract_id)
            log.info("Statistics cleared for contract %s", contract_id)
        finally:
            await ha.disconnect()
            await api.close()
        return

    # Initial sync
    await run_sync(config)

    # Schedule daily sync at random time around 6am and 9am
    random_minute = random.randint(0, 59)
    random_second = random.randint(0, 59)

    scheduler = AsyncIOScheduler(timezone="Europe/Paris")
    scheduler.add_job(
        run_sync,
        "cron",
        hour="6,14",
        minute=random_minute,
        second=random_second,
        args=[config],
    )
    scheduler.start()

    log.info(
        "Sync scheduled daily at 06:%02d:%02d and 14:%02d:%02d",
        random_minute, random_second, random_minute, random_second,
    )

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
