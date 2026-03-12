"""Load and validate options.json configuration."""

import json
import logging
import os
import sys

log = logging.getLogger("eaudemarseille")

OPTIONS_PATH = os.environ.get("OPTIONS_PATH", "/data/options.json")


def get_config() -> dict:
    """Load and validate configuration from options.json."""
    try:
        with open(OPTIONS_PATH, encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        log.error("Configuration file not found: %s", OPTIONS_PATH)
        sys.exit(1)
    except json.JSONDecodeError as e:
        log.error("Invalid JSON in %s: %s", OPTIONS_PATH, e)
        sys.exit(1)

    username = config.get("username", "").strip()
    password = config.get("password", "").strip()
    if not username or not password:
        log.error("'username' and 'password' are required in options.json")
        sys.exit(1)

    price_per_m3 = config.get("price_per_m3")
    if price_per_m3 is not None:
        try:
            price_per_m3 = float(price_per_m3)
        except (TypeError, ValueError):
            log.error("'price_per_m3' must be a number")
            sys.exit(1)

    name = config.get("name", "Eau de Marseille").strip()
    action = config.get("action", "sync").strip()
    if action not in ("sync", "reset"):
        log.error("'action' must be 'sync' or 'reset'")
        sys.exit(1)

    return {
        "username": username,
        "password": password,
        "price_per_m3": price_per_m3,
        "name": name,
        "action": action,
    }
