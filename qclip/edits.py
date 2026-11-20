"""Décisions du tri et réglages de l'éditeur, par moment (SPEC §7, écrans 4 et 5) → work/<id>/edits.json.

Clé = numéro de la plage (`window`) : stable quand on recalcule les candidats (un candidat par plage).
"""

import json
from pathlib import Path
from typing import Any, Literal

from qclip.sources import WORK_DIR

Decision = Literal["keep", "reject", "skip"]
DECISIONS = ("keep", "reject", "skip")
LAYOUTS = ("facecam", "blur", "crop")
STYLES = ("neon", "box", "outline", "karaoke")
PAD = 0.15  # marge autour des mots quand on recale une borne


def edits_path(vid: str) -> Path:
    return WORK_DIR / vid / "edits.json"


def load_edits(vid: str) -> dict[int, dict[str, Any]]:
    path = edits_path(vid)
    if not path.exists():
        return {}
    return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def save_edit(vid: str, window: int, **changes: Any) -> dict[str, Any]:
    """Met à jour les réglages d'un moment. Une valeur None efface le réglage (retour au défaut)."""
    checks = {"decision": DECISIONS, "layout": LAYOUTS, "style": STYLES}
    for key, value in changes.items():
        if key not in {"decision", "layout", "style", "hook", "start", "end", "corrections"}:
            raise ValueError(f"réglage inconnu : {key}")
        if (
            key == "corrections"
            and value is not None
            and (not isinstance(value, dict) or not all(isinstance(t, str) and t.strip() for t in value.values()))
        ):
            raise ValueError("corrections attend {début du mot (s): texte corrigé}")
        if key in checks and value is not None and value not in checks[key]:
            raise ValueError(f"{key} invalide {value!r} : {', '.join(checks[key])}")
        if key == "hook" and value is not None and len(value) > 80:
            raise ValueError("accroche trop longue (80 caractères max)")
    edits = load_edits(vid)
    current = {**edits.get(window, {}), **changes}
    current = {k: v for k, v in current.items() if v is not None}
    if current:
        edits[window] = current
    else:
        edits.pop(window, None)
    path = edits_path(vid)
    path.write_text(json.dumps({str(k): v for k, v in sorted(edits.items())}, ensure_ascii=False, indent=2), "utf-8")
    return current


def word_key(start: float) -> str:
    """Clé d'un mot dans `corrections` : son début (temps VOD) à la milliseconde."""
    return f"{start:.3f}"


def corrected(words: list[dict[str, Any]], corrections: dict[str, str]) -> list[dict[str, Any]]:
    """Mots de la transcription avec les corrections de l'éditeur appliquées."""
    if not corrections:
        return words
    return [{**w, "text": corrections.get(word_key(w["start"]), w["text"])} for w in words]


def correct_everywhere(words: list[dict[str, Any]], old: str, new: str) -> dict[str, str]:
    """« Corriger partout » : toutes les occurrences du mot (ponctuation gardée) → corrections à enregistrer."""
    out = {}
    for w in words:
        core = w["text"].strip(".,!?…:;«»\"'")
        if core.lower() == old.lower():
            out[word_key(w["start"])] = w["text"].replace(core, new, 1)
    return out


def snap_bounds(
    start: float, end: float, words: list[dict[str, Any]], bounds: tuple[float, float]
) -> tuple[float, float]:
    """Bornes choisies à la souris → recalées pour ne jamais couper un mot, et gardées dans la plage."""
    for w in words:
        if w["start"] < start < w["end"]:
            start = w["start"] - PAD
        if w["start"] < end < w["end"]:
            end = w["end"] + PAD
    start, end = max(bounds[0], start), min(bounds[1], end)
    if end - start < 1.0:
        raise ValueError("passage trop court (moins d'une seconde)")
    return round(start, 3), round(end, 3)


def apply_edit(
    c: dict[str, Any], edit: dict[str, Any], words: list[dict[str, Any]], window_end: float
) -> dict[str, Any]:
    """Candidat avec les bornes ajustées à la main (si présentes) ; texte et position dans le fichier recalculés."""
    if "start" not in edit and "end" not in edit:
        return c
    window_start = c["start"] - c["file_start"]
    start, end = snap_bounds(
        edit.get("start", c["start"]), edit.get("end", c["end"]), words, (window_start, window_end)
    )
    inside = [w for w in words if start <= w["start"] and w["end"] <= end]
    return {
        **c,
        "start": start,
        "end": end,
        "duration": round(end - start, 2),
        "file_start": round(start - window_start, 3),
        "peak": min(max(c["peak"], start), end),
        "text": " ".join(w["text"] for w in inside),
        "edited": True,
    }
