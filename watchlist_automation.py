"""Persist opt-in target-list updates from the latest market screen."""

import json
import time
import uuid


def save_config(config_file, config):
    temporary = config_file.with_name(f"{config_file.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
        temporary.replace(config_file)
    finally:
        temporary.unlink(missing_ok=True)


def apply_watchlist_automation(config_file, suggestions):
    # An unavailable/empty screen must not clear the target list.
    candidates = list(dict.fromkeys(
        item["symbol"] for item in suggestions if item.get("symbol")
    ))
    if not candidates or not config_file.exists():
        return False
    config = json.loads(config_file.read_text(encoding="utf-8"))
    targets = list(config.get("target_symbols", []))
    updated = list(targets)
    if config.get("auto_add_candidates", False):
        updated = list(dict.fromkeys(updated + candidates))
    if config.get("auto_remove_avoided", False):
        updated = [symbol for symbol in updated if symbol in candidates]
    if updated == targets:
        return False
    config["target_symbols"] = updated
    config["updated_at"] = int(time.time())
    save_config(config_file, config)
    return True
