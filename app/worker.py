from __future__ import annotations

import asyncio
import signal

from app.core.config import get_settings
from app.core.startup import validate_settings
from app.services.background_coordinator import background_job_coordinator
from app.services.market_data import market_data_service
from app.services.worker_heartbeat import worker_heartbeat_service

settings = get_settings()


async def main() -> None:
    """Run dedicated background responsibilities and fail closed on bad config.

    The coordinator owns a PostgreSQL advisory lock before starting singleton
    lifecycle, broadcast, and retention jobs. This protects zero-downtime worker
    deployments where old and new Render worker instances can briefly overlap.
    """
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

    # Both web and worker keep a lightweight BTC feed in V1. Web uses its copy
    # for on-demand scans; the dedicated worker uses its copy for entry/expiry.
    await market_data_service.start(settings.default_pair)
    await worker_heartbeat_service.start()
    await background_job_coordinator.start()
    try:
        await stop.wait()
    finally:
        await background_job_coordinator.stop()
        await worker_heartbeat_service.stop()
        await market_data_service.stop()


if __name__ == '__main__':
    asyncio.run(main())
