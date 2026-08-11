"""P00 worker process with deterministic graceful shutdown."""

import asyncio
import logging
import signal

from swim_coach.settings import get_settings

logger = logging.getLogger(__name__)


class Worker:
    """Idle P00 process shell; real job processing starts in a later phase."""

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("worker_started")
        await stop_event.wait()
        logger.info("worker_stopped")


async def run_worker() -> None:
    """Run until SIGINT/SIGTERM while allowing in-flight shutdown cleanup."""

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await Worker().run(stop_event)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
