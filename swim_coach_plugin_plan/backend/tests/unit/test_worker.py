import asyncio

import pytest

from swim_coach.interfaces.worker.main import Worker


@pytest.mark.asyncio
async def test_worker_stops_when_signaled() -> None:
    stop_event = asyncio.Event()
    task = asyncio.create_task(Worker().run(stop_event))

    await asyncio.sleep(0)
    assert not task.done()

    stop_event.set()
    await asyncio.wait_for(task, timeout=1)

    assert task.done()
