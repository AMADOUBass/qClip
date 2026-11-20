"""Mesure du temps de chaque étape.

Le cœur annonce ses étapes ; la CLI (ou plus tard l'API) décide comment les afficher.
"""

import re
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
        on_video: Callable[[str], None] | None = None,
    ) -> None:
        self.on_start = on_start
        self.on_done = on_done
        self.on_info = on_info
        self.on_stage = on_stage
        self.on_video = on_video
        self.timings: dict[str, float] = {}
        self.stage_times: dict[str, float] = {}  # durée de chaque grande étape terminée
        self._stage: tuple[str, float] | None = None
        self.zone_times: dict[str, dict[int, float]] = {}  # par grande étape : secondes passées sur chaque zone

    def stage(self, name: str) -> None:
        """Annonce une grande étape (repérage, téléchargement, transcription…) : l'interface affiche où on en est."""
        self.end_stage()
        self._stage = (name, time.perf_counter())
        if self.on_stage:
            self.on_stage(name)
        elif self.on_info:
            self.on_info(f"— {name} —")

    def end_stage(self) -> None:
        """Clôt la grande étape en cours et note sa durée."""
        if self._stage:
            name, start = self._stage
            self.stage_times[name] = round(time.perf_counter() - start, 1)
            self._stage = None

    def video(self, vid: str) -> None:
        """Annonce la VOD traitée dès qu'elle est connue (l'interface peut ouvrir son écran)."""
        if self.on_video:
            self.on_video(vid)

    @contextmanager
    def step(self, name: str) -> Generator[None]:
        if self.on_start:
            self.on_start(name)
        start = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start
        self.timings[name] = self.timings.get(name, 0.0) + elapsed
        zone = zone_rank(name)
        if self._stage and zone is not None:
            per_zone = self.zone_times.setdefault(self._stage[0], {})
            per_zone[zone] = per_zone.get(zone, 0.0) + elapsed
        if self.on_done:
            self.on_done(name, elapsed)

    def info(self, message: str) -> None:
        if self.on_info:
            self.on_info(message)


CACHED_S = 0.5  # en dessous, l'étape n'a fait que relire son résultat
NUMBER_RE = re.compile(r"n°(\d+)")  # « plage 1/3 (n°22, 75 s) » : le compteur 1/3 n'est pas le rang
PLAGE_RE = re.compile(r"plage (\d+)")  # « plage 03/24 », « CLAP plage 05 »


def zone_rank(name: str) -> int | None:
    """Rang de la zone concernée par une étape, ou None si l'étape ne porte pas sur une zone."""
    match = NUMBER_RE.search(name) or PLAGE_RE.search(name)
    return int(match.group(1)) if match else None


def merge_timings(old: dict[str, float], new: dict[str, float]) -> dict[str, float]:
    """Garde la mesure réelle quand une reprise n'a fait que relire le cache (durée quasi nulle)."""
    return {**old, **{k: v for k, v in new.items() if v >= CACHED_S or k not in old}}
