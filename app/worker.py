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
    """Run dedicated background responsibilities and fail closed on bad config."""
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

    # BTCUSDT is the initial high-frequency analysis/reference feed. BC.GAME
    # BTC/USD Start/End Rate remains separate product truth.
    await market_data_service.start(settings.analysis_pair)
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
