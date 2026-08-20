from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import RuntimeSetting
from app.services.worker_heartbeat import WorkerHeartbeatService

settings = get_settings()


@dataclass(frozen=True)
class WorkerStatus:
    seen: bool
    fresh: bool
    healthy: bool
    age_seconds: float | None
    last_heartbeat: datetime | None
    components: dict[str, bool]


def get_worker_status(db: Session) -> WorkerStatus:
    record = db.get(RuntimeSetting, WorkerHeartbeatService.KEY)
    if record is None:
        return WorkerStatus(False, False, False, None, None, {})

    components: dict[str, bool] = {}
    healthy = False
    raw_timestamp: str | None = None
    try:
        payload = json.loads(record.value)
        if isinstance(payload, dict):
            raw_timestamp = payload.get('timestamp')
            healthy = bool(payload.get('healthy'))
            raw_components = payload.get('components')
            if isinstance(raw_components, dict):
                components = {str(key): bool(value) for key, value in raw_components.items()}
    except (json.JSONDecodeError, TypeError):
        # Backward-compatible read of the old timestamp-only heartbeat. A legacy
        # heartbeat is considered alive but not healthy enough for LIVE gating.
        raw_timestamp = record.value
        healthy = False

    if not raw_timestamp:
        return WorkerStatus(True, False, False, None, None, components)
    try:
        heartbeat = datetime.fromisoformat(raw_timestamp)
    except (ValueError, TypeError):
        return WorkerStatus(True, False, False, None, None, components)
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    heartbeat = heartbeat.astimezone(timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - heartbeat).total_seconds())
    fresh = age <= settings.worker_heartbeat_max_age_seconds
    return WorkerStatus(True, fresh, healthy and fresh, age, heartbeat, components)
