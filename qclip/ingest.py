"""Ingest par fenêtre (SPEC §4.3) : audio de la plage → voix (mono 16 kHz) + reste (mono 48 kHz)."""

import json
from pathlib import Path
from typing import Any

from qclip.separation import VocalSeparator
from qclip.sources import WORK_DIR
from qclip.steps import Steps
from qclip.utils.ffmpeg import last_line, run


def load_fetched(vid: str, top: int | None = None) -> list[dict[str, Any]]:
    """Plages téléchargées par `qclip fetch` (work/<id>/windows/windows.json), triées par rang."""
    path = WORK_DIR / vid / "windows" / "windows.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} absent : lancer d'abord `qclip fetch`")
    windows = sorted(json.loads(path.read_text(encoding="utf-8")), key=lambda w: w["rank"])
    return windows[:top] if top else windows


def to_wav(src: Path, dst: Path, sample_rate: int, mono: bool = True) -> Path:
    args: list[str | Path] = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vn"]
    if mono:
        args += ["-ac", "1"]
    args += ["-ar", str(sample_rate), "-c:a", "pcm_s16le", dst]
    result = run(args, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg n'a pas pu convertir {src.name} : {last_line(result.stderr)}")
    return dst


def stem_paths(windows_dir: Path, rank: int) -> tuple[Path, Path]:
    return windows_dir / f"w_{rank:02d}.vocals.wav", windows_dir / f"w_{rank:02d}.other.wav"


def ingest_windows(
    vid: str,
    steps: Steps,
    separation: bool = True,
    model: str = "Kim_Vocal_2.onnx",
    top: int | None = None,
    force: bool = False,
) -> list[tuple[Path, Path]]:
    """Prépare vocals.wav / other.wav pour chaque plage. Réutilise ce qui existe déjà (sauf `force`)."""
    windows_dir = WORK_DIR / vid / "windows"
    todo = []
    results = []
    for w in load_fetched(vid, top):
        vocals, other = stem_paths(windows_dir, w["rank"])
        results.append((vocals, other))
        if force or not (vocals.exists() and other.exists()):
            todo.append((w, vocals, other))
    if not todo:
        steps.info("toutes les plages sont déjà prêtes (--force pour refaire)")
        return results

    separator = None
    if separation:
        with steps.step(f"chargement du modèle de séparation {model}"):
            separator = VocalSeparator(model)
    try:
        for i, (w, vocals, other) in enumerate(todo, 1):
            video = windows_dir / w["file"]
            with steps.step(f"plage {i}/{len(todo)} (n°{w['rank']:02d}, {w['duration']:.0f} s)"):
                if separator is None:
                    to_wav(video, vocals, 16000)
                    to_wav(video, other, 48000)
                    continue
                full = to_wav(video, windows_dir / f"w_{w['rank']:02d}.full.wav", 44100, mono=False)
                sep_dir = windows_dir / "sep_tmp"
                raw_vocals, raw_other = separator.separate(full, sep_dir)
                to_wav(raw_vocals, vocals, 16000)
                to_wav(raw_other, other, 48000)
                for tmp in (full, raw_vocals, raw_other):
                    tmp.unlink(missing_ok=True)
    finally:
        if separator is not None:
            separator.close()
    return results
