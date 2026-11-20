"""Suivi des clips par campagne (SPEC §4.10) : input/<campagne>/posts.csv.

Une ligne par clip rendu (plateforme vide), puis une ligne par plateforme où il est posté (`qclip log`).
Sert à ne pas reclipper un passage déjà posté et à suivre ce qui rapporte (`qclip stats`).
"""

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qclip.campaign import load_campaign
from qclip.config import ConfigError
from qclip.sources import INPUT_DIR

FIELDS = ["video_id", "clip_id", "vod_start", "vod_end", "duration", "title", "clip_file", "source_url",
          "rendered_at", "platform", "post_url", "views", "logged_at", "paid", "paid_at"]  # fmt: skip
PLATFORMS = ("tiktok", "shorts", "reels")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def posts_path(slug: str) -> Path:
    return INPUT_DIR / slug / "posts.csv"


def read_posts(slug: str) -> list[dict[str, str]]:
    path = posts_path(slug)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: row.get(k, "") or "" for k in FIELDS} for row in csv.DictReader(f)]


def write_posts(slug: str, rows: list[dict[str, str]]) -> Path:
    path = posts_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")  # écriture atomique : le fichier ouvert dans Excel ne doit pas être corrompu
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
    return path


def record_render(slug: str, row: dict[str, Any]) -> None:
    """Ajoute (ou met à jour) la ligne « rendu » d'un clip ; les lignes déjà postées ne sont pas touchées."""
    rows = read_posts(slug)
    key = (str(row["video_id"]), str(row["clip_id"]))
    clean = {k: str(row.get(k, "")) for k in FIELDS}
    clean["rendered_at"] = now()
    for i, r in enumerate(rows):
        if (r["video_id"], r["clip_id"]) == key and not r["post_url"]:
            rows[i] = {**clean, "platform": r["platform"]}
            break
    else:
        rows.append(clean)
    write_posts(slug, rows)


def find_rendered(rows: list[dict[str, str]], clip: str) -> dict[str, str]:
    """`clip` = « 3 » (si une seule VOD a ce numéro) ou « twitch-123/3 »."""
    vid, _, cid = clip.rpartition("/")
    matches = [r for r in rows if r["clip_id"] == cid and (not vid or r["video_id"] == vid)]
    vids = {r["video_id"] for r in matches}
    if not matches:
        raise ConfigError(f"clip {clip!r} introuvable dans posts.csv : le rendre d'abord (`qclip render`)")
    if len(vids) > 1:
        raise ConfigError(f"clip {clip!r} ambigu ({', '.join(sorted(vids))}) : préciser <video_id>/{cid}")
    return matches[0]


def log_post(
    slug: str, clip: str, platform: str, url: str | None, views: int | None, paid: float | None = None
) -> dict[str, str]:
    """Enregistre l'URL d'un post, ses vues et/ou ce qui a été payé pour ce post."""
    brief = load_campaign(slug)
    if brief.test_only:
        raise ConfigError(f"{slug!r} est une campagne de test : ses clips ne doivent pas être postés")
    if platform not in PLATFORMS:
        raise ConfigError(f"plateforme inconnue {platform!r} : {', '.join(PLATFORMS)}")
    if url is not None and not url.startswith(("https://", "http://")):
        raise ConfigError(f"URL invalide : {url!r}")
    rows = read_posts(slug)
    base = find_rendered(rows, clip)
    same = [r for r in rows if (r["video_id"], r["clip_id"]) == (base["video_id"], base["clip_id"])]
    target = next((r for r in same if r["platform"] == platform), None)
    if target is None:
        target = next((r for r in same if not r["platform"]), None)
        if target is None:
            target = dict(base)
            rows.append(target)
        target["platform"] = platform
    if url is None and not target["post_url"]:
        raise ConfigError("donner --url la première fois (les vues seules se saisissent ensuite)")
    if url is not None:
        target["post_url"] = url
    if views is not None:
        target["views"] = str(views)
    if paid is not None:
        if paid < 0:
            raise ConfigError("montant payé négatif")
        target["paid"] = f"{paid:.2f}"
        target["paid_at"] = now()
    target["logged_at"] = now()
    write_posts(slug, rows)
    return target


def estimate(views: int, rate_per_1k: float, payout_min: float | None, payout_max: float | None) -> float:
    """Gain estimé d'un post : vues / 1000 × tarif, 0 sous le minimum du brief, plafonné au maximum."""
    value = views / 1000 * rate_per_1k
    if payout_min is not None and value < payout_min:
        return 0.0
    if payout_max is not None:
        value = min(value, payout_max)
    return round(value, 2)


@dataclass
class Stats:
    rendered: int
    posted: int  # posts (une ligne par plateforme)
    views: int
    earnings: float  # gains estimés (vues × tarif, min / max du brief)
    by_platform: dict[str, tuple[int, int]]  # plateforme → (posts, vues)
    paid: float = 0.0  # réellement payé (saisi)
    budget_total: float | None = None
    budget_left: float | None = None


def campaign_stats(slug: str) -> Stats:
    brief = load_campaign(slug)
    rows = read_posts(slug)
    rendered = len({(r["video_id"], r["clip_id"]) for r in rows})
    posted_rows = [r for r in rows if r["post_url"]]
    by_platform: dict[str, tuple[int, int]] = {}
    for r in posted_rows:
        n, v = by_platform.get(r["platform"], (0, 0))
        by_platform[r["platform"]] = (n + 1, v + int(r["views"] or 0))
    views = sum(v for _, v in by_platform.values())
    earnings = sum(
        estimate(int(r["views"] or 0), brief.rate_per_1k, brief.payout_min, brief.payout_max) for r in posted_rows
    )
    paid = round(sum(float(r["paid"] or 0) for r in rows), 2)
    left = round(brief.budget_total - paid, 2) if brief.budget_total is not None else None
    return Stats(rendered, len(posted_rows), views, round(earnings, 2), by_platform, paid, brief.budget_total, left)


def posted_ranges(slug: str, video_id: str) -> list[tuple[float, float]]:
    """Passages déjà postés de cette VOD (à ne pas reclipper)."""
    return [
        (float(r["vod_start"]), float(r["vod_end"]))
        for r in read_posts(slug)
        if r["video_id"] == video_id and r["post_url"] and r["vod_start"] and r["vod_end"]
    ]
