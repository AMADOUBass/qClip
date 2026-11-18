"""Replay du chat Twitch : téléchargement (TwitchDownloaderCLI) et lecture du JSON."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from qclip import ROOT
from qclip.utils.ffmpeg import last_line, run

TWITCH_DOWNLOADER = ROOT / "tools" / "TwitchDownloaderCLI.exe"
REPEATS = re.compile(r"(.)\1+")
EDGE_PUNCT = re.compile(r"^\W+|\W+$")


@dataclass
class ChatMessage:
    offset: float  # secondes depuis le début de la VOD
    text: str
    user: str = ""  # login Twitch (minuscules)


def download_chat(vod_id: str, out_path: Path, threads: int = 4) -> Path:
    """`chatdownload` en JSON. Peut prendre plusieurs minutes sur une longue VOD avec un chat actif."""
    if out_path.exists():
        return out_path
    if not TWITCH_DOWNLOADER.exists():
        raise RuntimeError(f"TwitchDownloaderCLI absent : le placer dans {TWITCH_DOWNLOADER}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".part.json")  # pas de fichier à moitié écrit pris pour un cache valide
    result = run(
        [TWITCH_DOWNLOADER, "chatdownload", "--id", vod_id, "-o", tmp, "--threads", str(threads),
         "--collision", "Overwrite", "--banner", "false", "--log-level", "Error"],
        timeout=3 * 3600,
    )  # fmt: skip
    if result.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"chatdownload a échoué : {last_line(result.stderr or result.stdout)}")
    tmp.replace(out_path)
    return out_path


def load_chat(path: Path) -> list[ChatMessage]:
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = [
        ChatMessage(
            float(c["content_offset_seconds"]),
            str(c.get("message", {}).get("body", "")),
            str(c.get("commenter", {}).get("name", "")).lower(),
        )
        for c in data.get("comments", [])
    ]
    return sorted(messages, key=lambda m: m.offset)


def is_noise(msg: ChatMessage, bots: list[str]) -> bool:
    """Messages qui ne disent rien de la réaction du public : bots et commandes (« !discord »)."""
    return msg.user in bots or msg.text.lstrip().startswith("!")


def normalize(word: str) -> str:
    """« Wshhhhhh! » → « wsh », « MDRRRR » → « mdr » (minuscules, ponctuation de bord ôtée, répétitions réduites)."""
    return REPEATS.sub(r"\1", EDGE_PUNCT.sub("", word.lower()))


def is_reaction(text: str, emotes: list[str]) -> bool:
    """Le message contient une emote / un mot de rire ou de choc.

    Emoji (« 🤣 ») : n'importe où. Mot (« LUL », « mdr ») : mot entier normalisé, ou début de mot si l'emote fait
    au moins 3 lettres (« ahahaha », « LULW »). « W » seul ne correspond donc pas à « Wesh ».
    """
    words = [normalize(w) for w in text.split()]
    for emote in emotes:
        if not emote.isascii():
            if emote in text:
                return True
            continue
        target = normalize(emote)
        if any(w == target or (len(target) >= 3 and w.startswith(target)) for w in words):
            return True
    return False
