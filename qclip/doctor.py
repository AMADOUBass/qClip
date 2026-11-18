"""Vérifications de l'environnement. Ne fait aucun affichage : renvoie des `Check` que la CLI (ou l'API) présente."""

import json
import os
import platform
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Literal

import psutil

from qclip import ROOT
from qclip.campaign import CAMPAIGNS_DIR, brief_paths, load_brief
from qclip.config import CONFIG_PATH, ConfigError, load_config
from qclip.utils import ffmpeg

Status = Literal["ok", "warn", "fail"]
GB = 1024**3
OLLAMA_URL = "http://127.0.0.1:11434"  # pas "localhost" : Windows essaie ::1 en premier (+2 s)
SAMPLE = ROOT / "input" / "sample.mp4"
FFMPEG_FIX = "winget install Gyan.FFmpeg.Essentials  (puis rouvrir le terminal pour recharger le PATH)"


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    fix: str = ""  # « comment corriger », surtout pour les ❌
    seconds: float = 0.0


def check_python() -> Check:
    version = platform.python_version()
    if sys.version_info[:2] == (3, 12):
        return Check("Python", "ok", f"{version} ({sys.executable})")
    return Check("Python", "fail", version, "uv python install 3.12 && uv sync")


def check_uv() -> Check:
    exe = ffmpeg.find_tool("uv")
    if exe is None:
        return Check("uv", "fail", "introuvable", 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
    return Check("uv", "ok", ffmpeg.run([exe, "--version"], timeout=30).stdout.strip())


def cpu_name() -> str:
    if sys.platform == "win32":
        import winreg

        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "inconnu"


def check_cpu() -> Check:
    physical = psutil.cpu_count(logical=False) or 0
    logical = psutil.cpu_count(logical=True) or 0
    return Check("Processeur", "ok", f"{cpu_name()} — {physical} cœurs physiques, {logical} logiques")


def check_ram() -> Check:
    mem = psutil.virtual_memory()
    detail = f"{mem.total / GB:.1f} Go au total, {mem.available / GB:.1f} Go libres"
    if mem.total < 8 * GB:
        return Check("RAM", "warn", f"{detail} — moins de 8 Go : un seul modèle à la fois, fermer le navigateur")
    return Check("RAM", "ok", detail)


def check_tool(name: str) -> Check:
    exe = ffmpeg.find_tool(name)
    if exe is None:
        return Check(name, "fail", "introuvable dans le PATH", FFMPEG_FIX)
    return Check(name, "ok", f"{ffmpeg.tool_version(exe)} ({exe})")


def check_encoder() -> Check:
    if ffmpeg.find_tool("ffmpeg") is None:
        return Check("Encodage vidéo", "fail", "ffmpeg absent : test impossible", FFMPEG_FIX)
    start = time.perf_counter()
    ok, err = ffmpeg.try_encode("h264_qsv")
    if ok:
        return Check(
            "Encodage vidéo",
            "ok",
            f"h264_qsv (Quick Sync) : 1 s de 1080x1920 en {time.perf_counter() - start:.1f} s",
        )
    start = time.perf_counter()
    ok_x264, err_x264 = ffmpeg.try_encode("libx264")
    if ok_x264:
        return Check(
            "Encodage vidéo",
            "warn",
            f"h264_qsv indisponible ({err}) — repli libx264 OK : "
            f"1 s de 1080x1920 en {time.perf_counter() - start:.1f} s",
            "Pour QSV : mettre à jour le pilote graphique Intel (Intel Driver & Support Assistant)",
        )
    return Check(
        "Encodage vidéo",
        "fail",
        f"h264_qsv : {err} ; libx264 : {err_x264}",
        "Installer un build ffmpeg complet : winget install Gyan.FFmpeg.Essentials",
    )


def check_libass() -> Check:
    if ffmpeg.find_tool("ffmpeg") is None:
        return Check("libass (sous-titres)", "fail", "ffmpeg absent : test impossible", FFMPEG_FIX)
    if not ffmpeg.has_filter("subtitles"):
        return Check("libass (sous-titres)", "fail", "filtre subtitles absent de ce build", FFMPEG_FIX)
    ok, err = ffmpeg.try_subtitles()
    if ok:
        return Check("libass (sous-titres)", "ok", "filtre subtitles : sous-titre ASS brûlé sur 1 s de vidéo")
    return Check("libass (sous-titres)", "fail", f"le test a échoué : {err}", FFMPEG_FIX)


def check_ytdlp() -> Check:
    try:
        return Check("yt-dlp", "ok", f"module Python {metadata.version('yt-dlp')}")
    except metadata.PackageNotFoundError:
        pass
    exe = ffmpeg.find_tool("yt-dlp")
    if exe is not None:
        return Check("yt-dlp", "ok", f"{ffmpeg.run([exe, '--version'], timeout=30).stdout.strip()} ({exe})")
    return Check("yt-dlp", "warn", "absent — prévu au jalon M1")


def check_twitch_downloader() -> Check:
    exe = ROOT / "tools" / "TwitchDownloaderCLI.exe"
    if not exe.exists():
        found = ffmpeg.find_tool("TwitchDownloaderCLI")
        if found is None:
            return Check("TwitchDownloaderCLI", "warn", "absent de tools/ — prévu au jalon M1")
        exe = found
    version = ffmpeg.run([exe, "--version"], timeout=30).stdout.strip().splitlines()
    return Check("TwitchDownloaderCLI", "ok", f"{version[0] if version else 'version ?'} ({exe})")


def find_ollama() -> Path | None:
    exe = ffmpeg.find_tool("ollama")
    if exe is not None:
        return exe
    default = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return default if default.exists() else None


def check_ollama() -> Check:
    exe = find_ollama()
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as resp:
            models = [m["name"] for m in json.load(resp).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        if exe is None:
            return Check("Ollama", "warn", "absent — optionnel (rerank et titres par LLM, jalon M5)")
        return Check("Ollama", "warn", f"installé ({exe}) mais serveur arrêté sur {OLLAMA_URL} — optionnel")
    return Check("Ollama", "ok", f"serveur joignable, modèles : {', '.join(models) or 'aucun'}")


def check_disk() -> Check:
    free = shutil.disk_usage(ROOT).free / GB
    if free < 30:
        return Check("Espace disque", "warn", f"{free:.1f} Go libres sur le disque du projet — moins de 30 Go")
    return Check("Espace disque", "ok", f"{free:.1f} Go libres")


def check_sample() -> Check:
    if not SAMPLE.exists():
        return Check("input/sample.mp4", "warn", "absent — y déposer 5 min d'une VOD de campagne")
    if ffmpeg.find_tool("ffprobe") is None:
        return Check("input/sample.mp4", "warn", "présent, mais ffprobe absent : impossible de l'analyser")
    try:
        info = ffmpeg.ffprobe(SAMPLE)
    except (RuntimeError, ValueError) as e:
        return Check("input/sample.mp4", "fail", str(e), "Le fichier est peut-être corrompu : le remplacer")
    minutes, seconds = divmod(round(info.duration), 60)
    return Check(
        "input/sample.mp4",
        "ok",
        f"{minutes} min {seconds:02d} s, {info.width}x{info.height}, {info.fps:g} fps, {info.video_codec}, "
        f"{info.audio_streams} piste(s) audio",
    )


def check_config() -> Check:
    try:
        load_config(CONFIG_PATH)
    except ConfigError as e:
        return Check("config.yaml", "fail", "invalide", str(e))
    return Check("config.yaml", "ok", "valide")


def check_briefs() -> list[Check]:
    paths = brief_paths(CAMPAIGNS_DIR)
    if not paths:
        return [Check("Briefs", "warn", "aucun fichier dans campaigns/")]
    checks = []
    for path in paths:
        name = f"campaigns/{path.name}"
        try:
            brief = load_brief(path)
        except ConfigError as e:
            checks.append(Check(name, "fail", "invalide", str(e)))
        else:
            checks.append(Check(name, "ok", f"valide — « {brief.name} »"))
    return checks


CHECKS: list[Callable[[], Check | list[Check]]] = [
    check_python,
    check_uv,
    check_cpu,
    check_ram,
    lambda: check_tool("ffmpeg"),
    lambda: check_tool("ffprobe"),
    check_encoder,
    check_libass,
    check_ytdlp,
    check_twitch_downloader,
    check_ollama,
    check_disk,
    check_sample,
    check_config,
    check_briefs,
]


def run_checks() -> list[Check]:
    """Lance toutes les vérifications et mesure le temps de chacune."""
    results: list[Check] = []
    for check in CHECKS:
        start = time.perf_counter()
        try:
            out = check()
        except Exception as e:  # un test qui plante (timeout…) ne doit pas faire tomber tout le doctor
            out = Check(getattr(check, "__name__", "?"), "fail", f"erreur inattendue : {e!r}")
        elapsed = time.perf_counter() - start
        items = out if isinstance(out, list) else [out]
        for item in items:
            item.seconds = elapsed / len(items)
        results.extend(items)
    return results
