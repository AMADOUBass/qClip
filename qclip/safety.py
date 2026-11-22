"""Sécurité / démonétisation (SPEC §4.9), sans LLM vision : ce que YouTube pénalise au début d'un clip.

Règle : violence (son d'explosion, de coups de feu, d'accident, repéré par CLAP) ou gros mots dans les 7 premières
secondes → pubs limitées. On signale et on propose le plus petit décalage du début qui dégage ces 7 secondes,
sans descendre sous la durée minimale du brief. Le reste (images violentes, contenu interdit) : revue humaine.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np

from qclip.meta import PROFANITY

FIRST_SECONDS = 7.0  # YouTube : ce qui se passe dans les 7 premières secondes compte pour la monétisation
# Libellés CLAP → FR. Seulement explosion / coups de feu (SPEC §4.9) : « car crash » dépasse 0,5 sur 5 % d'un stream
# Just Chatting (bruits de bureau, micro), mesuré sur la VOD de test → faux positifs.
VIOLENT = {"explosion": "explosion", "gunshots": "coups de feu"}
CLAP_MIN = 0.5  # probabilité CLAP à partir de laquelle un son violent est signalé
GAP = 0.2  # marge après l'évènement quand on décale le début
RULE = "YouTube limite les pubs si un clip montre de la violence ou dit des gros mots dans ses 7 premières secondes."


def events(
    words: list[dict[str, Any]], clap: np.ndarray | None, times: np.ndarray | None, labels: list[str]
) -> list[dict[str, Any]]:
    """Évènements à risque dans la plage (temps VOD) : gros mots et sons violents."""
    found = [
        {"kind": "gros mot", "start": w["start"], "end": w["end"], "detail": w["text"].strip(".,!?…:;«»\"' ")}
        for w in words
        if PROFANITY.search(w["text"])
    ]
    if clap is not None and times is not None and len(clap):
        for j, label in enumerate(labels):
            if label not in VIOLENT or j >= clap.shape[1]:
                continue
            for t, p in zip(times, clap[:, j], strict=True):
                if p >= CLAP_MIN:
                    found.append({"kind": "violence", "start": float(t) - 0.25, "end": float(t) + 0.25,
                                  "detail": f"{VIOLENT[label]} ({p:.2f})"})  # fmt: skip
    return sorted(found, key=lambda e: e["start"])


def check(start: float, end: float, found: list[dict[str, Any]], min_len: float) -> dict[str, Any]:
    """Verdict pour le passage [start, end] (temps VOD) et plus petit décalage du début qui le rend sûr."""

    def risky(s: float) -> list[dict[str, Any]]:
        return [e for e in found if e["end"] > s and e["start"] < s + FIRST_SECONDS]

    flags = risky(start)
    shift = None
    if flags:
        # Décalages candidats : juste après chaque évènement ; on garde le premier qui dégage les 7 s.
        for e in sorted(found, key=lambda x: x["end"]):
            s = e["end"] + GAP
            if s > start and end - s >= min_len and not risky(s):
                shift = round(s - start, 1)
                break
    return {
        "ok": not flags,
        "rule": RULE,
        "flags": [
            {"kind": e["kind"], "at": round(max(0.0, e["start"] - start), 1), "detail": e["detail"]} for e in flags
        ],
        "shift_s": shift,  # None : aucun décalage possible sans passer sous la durée minimale
        "vision": None,  # verdict du LLM vision (render.clip_safety) ; None = images non vérifiées : revue humaine
    }


def window_events(windows_dir: Path, rank: int, words: list[dict[str, Any]], labels: list[str]) -> list[dict[str, Any]]:
    """Évènements d'une plage à partir de sa transcription (corrigée) et de son cache CLAP (w_<n>.clap.npy)."""
    from qclip.signals import grid

    clap_path = windows_dir / f"w_{rank:02d}.clap.npy"
    fetched = {w["rank"]: w for w in json.loads((windows_dir / "windows.json").read_text(encoding="utf-8"))}
    clap = times = None
    if clap_path.exists() and rank in fetched:
        clap = np.load(clap_path)
        times = grid(fetched[rank]["start"], fetched[rank]["duration"])
        if len(times) != len(clap):
            clap = times = None  # cache d'une autre grille : on s'en passe plutôt que de se tromper d'instant
    return events(words, clap, times, labels)
