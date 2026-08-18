from __future__ import annotations

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
    age_seconds: float | None
    last_heartbeat: datetime | None


def get_worker_status(db: Session) -> WorkerStatus:
    record = db.get(RuntimeSetting, WorkerHeartbeatService.KEY)
    if record is None:
        return WorkerStatus(False, False, None, None)
    try:
        heartbeat = datetime.fromisoformat(record.value)
    except ValueError:
        return WorkerStatus(True, False, None, None)
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    heartbeat = heartbeat.astimezone(timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - heartbeat).total_seconds())
    return WorkerStatus(True, age <= settings.worker_heartbeat_max_age_seconds, age, heartbeat)
