"""Meta d'un clip (SPEC §4.10) sans LLM : accroche, titre (gabarits), hashtags, légende, conformité au brief,
miniature (image la plus nette près du pic). Un LLM (rerank, optionnel) peut fournir accroche et titre à la place."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from qclip.campaign import Brief
from qclip.chat import normalize

SENTENCE_END = (".", "?", "!", "…")
HOOK_SECONDS = 3.0
MAX_TITLE = 60
MIN_HASHTAGS, MAX_HASHTAGS = 5, 8
GENERIC_HASHTAGS = ["#fyp", "#pourtoi", "#twitch", "#clip", "#streamerfr", "#drole"]
QUOTE_MIN_CONF = (
    0.75  # une citation n'est retenue que si l'ASR est sûr de ses mots (évite « Maybe like so bad action »)
)
WORD_MIN_CONF = 0.45
TEST_BANNER = "⚠️ TEST — NE PAS POSTER (campagne de test, contenu non autorisé)"


@dataclass
class Sentence:
    text: str
    start: float  # secondes depuis le début du clip
    words: int
    mean_conf: float
    min_conf: float


def split_sentences(words: list[dict[str, Any]], clip_start: float) -> list[Sentence]:
    out: list[Sentence] = []
    current: list[dict[str, Any]] = []
    for w in words:
        current.append(w)
        if w["text"].rstrip().endswith(SENTENCE_END):
            out.append(make_sentence(current, clip_start))
            current = []
    if current:
        out.append(make_sentence(current, clip_start))
    return out


def make_sentence(words: list[dict[str, Any]], clip_start: float) -> Sentence:
    confs = [1.0 if w.get("confidence") is None else float(w["confidence"]) for w in words]
    return Sentence(
        " ".join(w["text"] for w in words).strip(),
        words[0]["start"] - clip_start,
        len(words),
        float(np.mean(confs)),
        float(min(confs)),
    )


def best_quote(
    words: list[dict[str, Any]], clip_start: float, keywords: list[str], max_words: int = 8, after: float = 0.0
) -> str:
    """La phrase la plus « citable » : courte, sûre (confiance ASR), vive (? ou !), avec un mot-clé si possible."""
    targets = {normalize(k) for k in keywords}
    best, best_score = "", -1.0
    for s in split_sentences(words, clip_start):
        if s.start < after or not 2 <= s.words <= max_words:
            continue
        if s.mean_conf < QUOTE_MIN_CONF or s.min_conf < WORD_MIN_CONF:
            continue
        score = s.mean_conf + (1.0 if s.text.endswith(("?", "!")) else 0.0)
        score += 0.5 if any(normalize(t) in targets for t in s.text.split()) else 0.0
        if score > best_score:
            best, best_score = s.text, score
    return best.rstrip(".…")


def make_hook(words: list[dict[str, Any]], clip_start: float, keywords: list[str]) -> str:
    """Accroche affichée 3 s en haut : une citation dite APRÈS les 3 premières secondes (elle teaser la suite et ne
    double pas le sous-titre affiché au même moment)."""
    return best_quote(words, clip_start, keywords, max_words=8, after=HOOK_SECONDS)


def make_title(creator: str, quote: str, reasons: list[str]) -> str:
    """Titre ≤ 60 caractères, sans promesse trompeuse : une citation du clip, sinon un gabarit tiré des signaux."""
    if quote:
        for title in (f"{creator} : « {quote} »", f"« {quote} »"):
            if len(title) <= MAX_TITLE:
                return title
        return truncate(f"« {quote} »", MAX_TITLE)
    joined = " ".join(reasons)
    if "rires" in joined:
        return truncate(f"{creator} en fou rire en live 😂", MAX_TITLE)
    if "cris" in joined or "voix forte" in joined:
        return truncate(f"{creator} s'énerve en live 😤", MAX_TITLE)
    if "chat" in joined:
        return truncate(f"Le chat de {creator} n'en revient pas 😳", MAX_TITLE)
    return truncate(f"{creator} en live", MAX_TITLE)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:«")
    return cut + "…"


def tag_from(name: str) -> str:
    return "#" + re.sub(r"[^0-9a-zà-ÿ]", "", name.lower())


def make_hashtags(brief: Brief) -> list[str]:
    """Hashtags exigés par le brief d'abord, puis le créateur et des génériques : 5 à 8 au total, sans doublon."""
    tags: list[str] = []
    for tag in [*brief.required.hashtags, tag_from(brief.creator), *GENERIC_HASHTAGS]:
        if tag.lower() not in {t.lower() for t in tags} and len(tag) > 1:
            tags.append(tag)
        if len(tags) >= MAX_HASHTAGS:
            break
    if len(brief.required.hashtags) > MAX_HASHTAGS:  # le brief prime sur la limite
        return list(brief.required.hashtags)
    return tags[: max(MIN_HASHTAGS, len(brief.required.hashtags))]


def make_caption(title: str, brief: Brief, hashtags: list[str]) -> str:
    lines = [TEST_BANNER, ""] if brief.test_only else []
    lines.append(title)
    if brief.required.caption_note:
        lines.append(brief.required.caption_note)
    lines.append("")
    lines.append(" ".join(([brief.required.mention] if brief.required.mention else []) + hashtags))
    return "\n".join(lines).strip() + "\n"


def compliance(brief: Brief, duration: float, caption: str, title: str) -> dict[str, Any]:
    """Vérifications du brief faisables sans regarder la vidéo (le reste : safety, M6)."""
    checks = [
        ("durée", brief.clip.min_len <= duration <= brief.clip.max_len,
         f"{duration:.1f} s (brief : {brief.clip.min_len:g}-{brief.clip.max_len:g} s)"),
        ("mention", not brief.required.mention or brief.required.mention in caption, brief.required.mention or "—"),
        ("hashtags", all(t in caption for t in brief.required.hashtags), " ".join(brief.required.hashtags) or "—"),
        ("titre ≤ 60", len(title) <= MAX_TITLE, f"{len(title)} caractères"),
        ("musique ajoutée", True, "aucune (qClip n'ajoute jamais de musique)"),
        ("campagne réelle", not brief.test_only, "campagne de TEST : ne pas poster" if brief.test_only else "oui"),
    ]  # fmt: skip
    return {"ok": all(ok for _, ok, _ in checks), "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}


def sharpness(gray: np.ndarray) -> float:
    """Variance du laplacien : plus elle est grande, plus l'image est nette."""
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def sharpest_time(video: Path, around: float, duration: float, span: float = 3.0, step: float = 0.5) -> float:
    """Instant le plus net dans [around - span, around + span] (images réduites à 270x480 pour aller vite)."""
    import cv2

    from qclip.facecam import frame_at

    best_t, best_v = around, -1.0
    for t in np.arange(max(0.2, around - span), min(duration - 0.2, around + span) + 1e-6, step):
        frame = frame_at(video, float(t), 270, 480)
        if frame is None:
            continue
        value = sharpness(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        if value > best_v:
            best_t, best_v = float(t), value
    return best_t
