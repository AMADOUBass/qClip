"""Sous-titres ASS mot par mot (pysubs2), brûlés ensuite par ffmpeg/libass (SPEC §4.8).

Les temps des mots sont relatifs au début du clip. Le mot prononcé est surligné ; 2 à 4 mots par ligne,
coupure aussi en fin de phrase et sur les pauses ; zones sûres : jamais dans les 20 % du bas ni contre le bord droit.
"""

from dataclasses import dataclass
from pathlib import Path

import pysubs2

from qclip.config import SubtitleConfig

WIDTH, HEIGHT = 1080, 1920
SAFE_BOTTOM = int(HEIGHT * 0.80)  # rien sous cette ligne (boutons / légende des plateformes)
MARGIN_L, MARGIN_R = 70, 150  # le bord droit porte les boutons TikTok / Shorts
LINE_GAP = 0.6  # une pause plus longue ouvre une nouvelle ligne
HOLD = 0.4  # une ligne reste affichée au plus 0,4 s après son dernier mot
HOOK_SECONDS = 3.0


@dataclass
class TimedWord:
    text: str
    start: float  # secondes depuis le début du clip
    end: float


def ass_color(hex_rgb: str) -> pysubs2.Color:
    """« #FFD400 » → couleur pysubs2 (ASS stocke en BGR, pysubs2 s'en charge)."""
    h = hex_rgb.lstrip("#")
    return pysubs2.Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def override_color(hex_rgb: str) -> str:
    """Balise de couleur ASS en ligne : &HBBGGRR&."""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def group_lines(words: list[TimedWord], per_line: int) -> list[list[TimedWord]]:
    """Mots → lignes : au plus `per_line` mots, coupure après une fin de phrase ou avant une pause."""
    lines: list[list[TimedWord]] = []
    current: list[TimedWord] = []
    for w in words:
        if current and (len(current) >= per_line or w.start - current[-1].end >= LINE_GAP):
            lines.append(current)
            current = []
        current.append(w)
        # Fin de phrase : on coupe toujours. Virgule : on coupe si la ligne a déjà 2 mots.
        if w.text.rstrip().endswith((".", "?", "!", "…")) or (w.text.rstrip().endswith(",") and len(current) >= 2):
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "/")


def build_ass(
    words: list[TimedWord],
    style: SubtitleConfig,
    center_y: int,
    clip_duration: float,
    hook: str = "",
    hook_y: int = 420,
    mention: str = "",
    watermark: str = "",
) -> pysubs2.SSAFile:
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = str(WIDTH)
    subs.info["PlayResY"] = str(HEIGHT)
    subs.info["WrapStyle"] = "0"
    subs.info["ScaledBorderAndShadow"] = "yes"
    white, black = ass_color(style.color), pysubs2.Color(0, 0, 0)
    subs.styles["Words"] = pysubs2.SSAStyle(
        fontname=style.font, fontsize=style.size, primarycolor=white, outlinecolor=black,
        backcolor=pysubs2.Color(0, 0, 0, 128), bold=True, outline=style.outline, shadow=2,
        alignment=pysubs2.Alignment.MIDDLE_CENTER, marginl=MARGIN_L, marginr=MARGIN_R, marginv=0,
    )  # fmt: skip
    subs.styles["Hook"] = pysubs2.SSAStyle(
        fontname=style.font, fontsize=round(style.size * 0.8), primarycolor=black, outlinecolor=ass_color("#FFFFFF"),
        backcolor=ass_color("#FFFFFF"), bold=True, borderstyle=3, outline=14, shadow=0,
        alignment=pysubs2.Alignment.MIDDLE_CENTER, marginl=MARGIN_L, marginr=MARGIN_R, marginv=0,
    )  # fmt: skip
    subs.styles["Small"] = pysubs2.SSAStyle(
        fontname=style.font, fontsize=40, primarycolor=white, outlinecolor=black, bold=True, outline=3, shadow=0,
        alignment=pysubs2.Alignment.MIDDLE_LEFT, marginl=MARGIN_L, marginr=MARGIN_R, marginv=0,
    )  # fmt: skip

    highlight = override_color(style.highlight)
    lines = group_lines(words, style.words_per_line)
    for n, line in enumerate(lines):
        next_start = lines[n + 1][0].start if n + 1 < len(lines) else clip_duration
        line_end = min(line[-1].end + HOLD, next_start, clip_duration)
        for i, word in enumerate(line):
            start = word.start if i else line[0].start
            end = line[i + 1].start if i + 1 < len(line) else line_end
            if end <= start:
                continue
            parts = []
            for j, other in enumerate(line):
                text = escape(other.text.upper() if style.uppercase else other.text)
                parts.append(f"{{\\c{highlight}}}{text}{{\\c&HFFFFFF&}}" if j == i else text)
            subs.append(
                pysubs2.SSAEvent(
                    start=round(start * 1000),
                    end=round(end * 1000),
                    style="Words",
                    text=f"{{\\pos({WIDTH // 2},{center_y})}}" + " ".join(parts),
                )  # fmt: skip
            )
    if hook:
        subs.append(pysubs2.SSAEvent(start=0, end=round(min(HOOK_SECONDS, clip_duration) * 1000), style="Hook",
                                     text=f"{{\\pos({WIDTH // 2},{hook_y})}}{escape(hook.upper())}"))  # fmt: skip
    if mention:
        subs.append(pysubs2.SSAEvent(start=0, end=round(clip_duration * 1000), style="Small",
                                     text=f"{{\\pos({MARGIN_L},{SAFE_BOTTOM - 50})}}{escape(mention)}"))  # fmt: skip
    if watermark:
        subs.append(pysubs2.SSAEvent(start=0, end=round(clip_duration * 1000), style="Small",
                                     text=f"{{\\pos({MARGIN_L},150)\\c&H3030FF&}}{escape(watermark)}"))  # fmt: skip
    return subs


def save_ass(subs: pysubs2.SSAFile, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(path), encoding="utf-8")
    return path
