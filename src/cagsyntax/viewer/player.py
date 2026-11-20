from __future__ import annotations


class CinePlayer:
    """Playback state for a cine loop. No Qt; a timer calls tick() every interval_ms."""

    def __init__(self, frame_count: int, fps: float):
        self._n = max(1, frame_count)
        self._fps = fps
        self.index = 0
        self.playing = False

    @property
    def interval_ms(self) -> int:
        return round(1000 / self._fps)

    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def toggle(self) -> None:
        self.playing = not self.playing

    def seek(self, i: int) -> None:
        self.index = min(max(i, 0), self._n - 1)

    def step(self, delta: int) -> None:
        self.seek(self.index + delta)

    def tick(self) -> None:
        if self.playing:
            self.index = (self.index + 1) % self._n
