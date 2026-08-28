from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


LOGGER = logging.getLogger("photovault")


def log_event(event: str, **fields: object) -> None:
    """Emit one machine-readable event without changing normal CLI output."""
    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        **fields,
    }
    LOGGER.info(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
