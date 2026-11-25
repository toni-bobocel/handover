from collections import deque


class Ring:
    """The last `seconds` of everything one robot said and everything said
    about it. Lives in RAM; nothing reaches the disk unless an incident fires,
    which keeps the SSD of a site PC from wearing out on routine telemetry."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._d: deque[tuple[float, dict]] = deque()

    def push(self, t: float, record: dict) -> None:
        self._d.append((t, record))
        while self._d and self._d[0][0] < t - self.seconds:
            self._d.popleft()

    def window(self, start: float, end: float) -> list[dict]:
        return [r for t, r in self._d if start <= t <= end]

    def __len__(self) -> int:
        return len(self._d)
