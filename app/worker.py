from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.startup import validate_settings
from app.services.background_coordinator import background_job_coordinator
from app.services.market_data import market_data_service
from app.services.signal_worker import signal_lifecycle_worker
from app.services.worker_heartbeat import worker_heartbeat_service

settings = get_settings()


def _critical_worker_health() -> dict[str, bool]:
    """Only components required for the base LIVE service belong in this gate."""
    success = signal_lifecycle_worker.last_success_at
    signal_cycle_fresh = False
    if success is not None:
        if success.tzinfo is None:
            success = success.replace(tzinfo=timezone.utc)
        signal_cycle_fresh = (
            datetime.now(timezone.utc) - success.astimezone(timezone.utc)
        ).total_seconds() <= settings.worker_heartbeat_max_age_seconds
    elif signal_lifecycle_worker._task is not None and not signal_lifecycle_worker._task.done() and signal_lifecycle_worker.last_error is None:
        signal_cycle_fresh = True
    return {
        'coordinator_leader': background_job_coordinator.is_leader,
        'coordinator_ok': background_job_coordinator.last_error is None,
        'signal_lifecycle_ok': signal_lifecycle_worker.last_error is None and signal_cycle_fresh,
        'market_stream_ok': market_data_service.connected and market_data_service.last_error is None,
    }


async def main() -> None:
    check = validate_settings(settings)
    if not check.ok:
        raise RuntimeError('Invalid worker configuration: ' + '; '.join(check.errors))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    await market_data_service.start(settings.analysis_pair)
    await background_job_coordinator.start()
    worker_heartbeat_service.health_provider = _critical_worker_health
    await worker_heartbeat_service.start()
    try:
        await stop.wait()
    finally:
        await worker_heartbeat_service.stop()
        await background_job_coordinator.stop()
        await market_data_service.stop()


if __name__ == '__main__':
    asyncio.run(main())
