from __future__ import annotations

import asyncio
import signal

from app.core.config import get_settings
from app.core.startup import validate_settings
from app.services.broadcast_worker import broadcast_worker
from app.services.market_data import market_data_service
from app.services.retention_cleanup import retention_cleanup_service
from app.services.signal_worker import signal_lifecycle_worker

settings = get_settings()


async def main() -> None:
    """Run background responsibilities separately and fail closed on bad config."""
    check = validate_settings(settings)
    if not check.ok:
        raise RuntimeError('Invalid worker configuration: ' + '; '.join(check.errors))

    stop = asyncio.Event(); loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, stop.set)
        except NotImplementedError: pass

    await market_data_service.start(settings.default_pair)
    await signal_lifecycle_worker.start()
    await broadcast_worker.start()
    await retention_cleanup_service.start()
    try: await stop.wait()
    finally:
        await retention_cleanup_service.stop()
        await broadcast_worker.stop(); await signal_lifecycle_worker.stop(); await market_data_service.stop()


if __name__ == '__main__': asyncio.run(main())
