"""Appels ffmpeg / ffprobe (toujours en liste d'arguments, jamais shell=True)."""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProbeInfo:
    duration: float  # secondes
    width: int
    height: int
    fps: float
    video_codec: str
    audio_streams: int


def find_tool(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


def run(args: list[str | Path], timeout: float = 120, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


def tool_version(exe: Path) -> str:
    """Première ligne de `<exe> -version`, ex. « ffmpeg version 8.0.1-essentials_build-www.gyan.dev »."""
    out = run([exe, "-version"], timeout=30).stdout
    first = out.splitlines()[0] if out else "?"
    return first.split(" Copyright")[0].strip()


def parse_fps(rate: str) -> float:
    """« 30000/1001 » → 29.97 ; « 0/0 » ou vide → 0."""
    num, _, den = rate.partition("/")
    try:
        return float(num) / float(den) if den else float(num)
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_ffprobe(data: dict[str, Any]) -> ProbeInfo:
    """Sortie JSON de `ffprobe -show_format -show_streams` → infos utiles."""
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("aucune piste vidéo")
    fps = parse_fps(video.get("avg_frame_rate", "")) or parse_fps(video.get("r_frame_rate", ""))
    duration = data.get("format", {}).get("duration") or video.get("duration") or 0
    return ProbeInfo(
        duration=float(duration),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=round(fps, 3),
        video_codec=str(video.get("codec_name", "?")),
        audio_streams=sum(1 for s in streams if s.get("codec_type") == "audio"),
    )


def ffprobe(path: Path, ffprobe_exe: Path | str = "ffprobe") -> ProbeInfo:
    result = run(
        [ffprobe_exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe a échoué : {last_line(result.stderr)}")
    return parse_ffprobe(json.loads(result.stdout))


def last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "(pas de message)"


def try_encode(encoder: str, ffmpeg_exe: Path | str = "ffmpeg") -> tuple[bool, str]:
    """Encode réellement 1 s de mire 1080x1920 à 30 fps. Renvoie (succès, message d'erreur éventuel)."""
    result = run(
        [ffmpeg_exe, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30",
         "-t", "1", "-c:v", encoder, "-f", "null", "-"],
        timeout=120,
    )  # fmt: skip
    return result.returncode == 0, "" if result.returncode == 0 else last_line(result.stderr)


def has_filter(name: str, ffmpeg_exe: Path | str = "ffmpeg") -> bool:
    out = run([ffmpeg_exe, "-hide_banner", "-filters"], timeout=30).stdout
    return any(len(parts) > 1 and parts[1] == name for parts in (line.split() for line in out.splitlines()))


TEST_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 240

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BorderStyle, Outline, Alignment
Style: Default,Arial,24,&H00FFFFFF,&H00000000,1,2,2

[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,qClip test
"""


def try_subtitles(ffmpeg_exe: Path | str = "ffmpeg") -> tuple[bool, str]:
    """Brûle un vrai sous-titre ASS (libass) sur 1 s de vidéo."""
    with tempfile.TemporaryDirectory(prefix="qclip_") as tmp:
        # Chemin relatif + cwd : évite l'échappement des « C:\\ » dans la syntaxe des filtres ffmpeg.
        (Path(tmp) / "test.ass").write_text(TEST_ASS, encoding="utf-8")
        result = run(
            [ffmpeg_exe, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=black:size=320x240:rate=30",
             "-t", "1", "-vf", "subtitles=test.ass", "-f", "null", "-"],
            timeout=180,
            cwd=Path(tmp),
        )  # fmt: skip
    return result.returncode == 0, "" if result.returncode == 0 else last_line(result.stderr)
