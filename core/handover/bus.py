import asyncio
import contextlib
from collections.abc import AsyncIterator

from .model import Event, Telemetry

Message = Telemetry | Event


class Bus:
    """In-process fan-out. Every subscriber gets its own bounded queue; a slow
    one (a browser tab on bad wifi) loses its oldest messages instead of
    holding up the recorder or the geofence."""

    def __init__(self, depth: int = 512):
        self.depth = depth
        self._subs: set[asyncio.Queue[Message]] = set()

    def publish(self, msg: Message) -> None:
        for q in self._subs:
            if q.full():
                q.get_nowait()
            q.put_nowait(msg)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Message]]:
        q: asyncio.Queue[Message] = asyncio.Queue(self.depth)
        self._subs.add(q)
        try:
            yield q
        finally:
            self._subs.discard(q)
