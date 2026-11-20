"""Mesure du temps de chaque étape.

Le cœur annonce ses étapes ; la CLI (ou plus tard l'API) décide comment les afficher.
"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager


class Steps:
    def __init__(
        self,
        on_start: Callable[[str], None] | None = None,
        on_done: Callable[[str, float], None] | None = None,
        on_info: Callable[[str], None] | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> None:
        self.on_start = on_start
        self.on_done = on_done
        self.on_info = on_info
        self.on_stage = on_stage
        self.timings: dict[str, float] = {}

    def stage(self, name: str) -> None:
        """Annonce une grande étape (repérage, téléchargement, transcription…) : l'interface affiche où on en est."""
        if self.on_stage:
            self.on_stage(name)
        elif self.on_info:
            self.on_info(f"— {name} —")

    @contextmanager
    def step(self, name: str) -> Generator[None]:
        if self.on_start:
            self.on_start(name)
        start = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start
        self.timings[name] = self.timings.get(name, 0.0) + elapsed
        if self.on_done:
            self.on_done(name, elapsed)

    def info(self, message: str) -> None:
        if self.on_info:
            self.on_info(message)
