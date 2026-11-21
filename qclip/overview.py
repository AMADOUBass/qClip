"""Données prêtes à afficher pour l'interface (SPEC §7). Lecture seule : l'API ne fait que les renvoyer.

Les chemins de fichiers sont renvoyés relatifs à la racine du projet (« work/… ») : l'API les sert sous /media/.
"""

import json
import re
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from qclip import ROOT
from qclip.campaign import ASSETS_DIR, Brief, campaign_slugs, load_campaign
from qclip.config import load_config
from qclip.edits import apply_edit, corrected, load_edits
from qclip.meta import best_quote, compliance, make_caption, make_hashtags, make_hook, make_title
from qclip.posts import campaign_stats, estimate, read_posts
from qclip.render import FG_H, MAX_ZOOM, TOP_H, WATERMARK, clip_layout, clip_safety
from qclip.rerank import key as rerank_key
from qclip.rerank import load_rerank
from qclip.sources import WORK_DIR
from qclip.subtitles import HOLD, HOOK_SECONDS, LINE_GAP, MARGIN_L, MARGIN_R, SAFE_BOTTOM
from qclip.utils.ffmpeg import ffprobe

CLIP_META_RE = re.compile(r"clip_\d+\.json")  # infos d'un clip rendu (titre, conformité, sécurité)
RADAR_BINS = 480
PEAK_POINTS = 600
LOW_CONFIDENCE = 0.5


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def initials(name: str) -> str:
    letters = [c for c in name if c.isalnum()]
    return "".join(letters[:2]).upper() or "?"


# --- machine ---------------------------------------------------------------------------------------


def system_status() -> dict[str, Any]:
    import psutil

    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_used_gb": round((mem.total - mem.available) / 1024**3, 1),
        "ram_total_gb": round(mem.total / 1024**3, 1),
        "disk_free_gb": round(shutil.disk_usage(ROOT).free / 1024**3, 1),
    }


# --- campagnes --------------------------------------------------------------------------------------


def scouted(slug: str) -> list[str]:
    found = []
    for path in sorted(WORK_DIR.glob("*/scout.json")):
        if read_json(path, {}).get("campaign") == slug:
            found.append(path.parent.name)
    return found


def campaign_summary(slug: str) -> dict[str, Any]:
    brief = load_campaign(slug)
    stats = campaign_stats(slug)
    warning = None
    if stats.budget_total and stats.budget_left is not None and stats.budget_left < 0.3 * stats.budget_total:
        warning = "Budget bientôt épuisé — poste vite"
    note = "Nouvelle · aucun clip encore" if stats.rendered == 0 else None
    return {
        "slug": slug,
        "name": brief.name,
        "creator": brief.creator,
        "initials": initials(brief.creator),
        "platform": brief.source_platform,
        "language": brief.language,
        "rate_per_1k": brief.rate_per_1k,
        "payout_min": brief.payout_min,
        "payout_max": brief.payout_max,
        "budget_total": stats.budget_total,
        "budget_left": stats.budget_left,
        "clips": stats.rendered,
        "posted": stats.posted,
        "views": stats.views,
        "earnings": stats.earnings,
        "paid": stats.paid,
        "test_only": brief.test_only,
        "warning": warning,
        "note": note,
        "vods": scouted(slug),
    }


def brief_view(slug: str) -> dict[str, Any]:
    brief = load_campaign(slug)
    data = brief.model_dump(mode="json")
    if brief.overlay:
        image = ASSETS_DIR / slug / brief.overlay.file
        data["overlay"]["url"] = rel(image) if image.exists() else None
    return {"slug": slug, "brief": data, "checklist": checklist(brief)}


def checklist(brief: Brief) -> list[dict[str, str]]:
    """Checklist « avant de poster » (écran Brief, panneau de droite), tirée du brief."""
    items = []
    r = brief.required
    if brief.requirements.dedicated_account:
        detail = f"Avec le lien {brief.requirements.link_in_bio} en bio" if brief.requirements.link_in_bio else ""
        items.append({"label": f"Compte dédié à {brief.creator}", "detail": detail})
    elif brief.requirements.link_in_bio:
        items.append({"label": f"Lien {brief.requirements.link_in_bio} en bio", "detail": ""})
    if brief.source_rule:
        items.append({"label": f"Source : {brief.source_rule}", "detail": "Vérifié sur chaque VOD ajoutée"})
    if brief.overlay:
        items.append({"label": "Overlay visible", "detail": "Incrusté automatiquement au rendu"})
    for tag in r.hashtags:
        items.append({"label": f"{tag} dans la description", "detail": "Ajouté à la légende générée"})
    if r.mention:
        items.append({"label": f"Mention {r.mention}", "detail": "Ajoutée à la légende générée"})
    for rule in brief.forbidden:
        items.append({"label": f"Interdit : {rule}", "detail": "À vérifier par toi avant de poster"})
    if brief.requirements.submit_within_min:
        delay = brief.requirements.submit_within_min
        items.append({"label": "Lien soumis sur la plateforme de campagne",
                      "detail": f"Dans les {delay} min après la publication"})  # fmt: skip
    return items


# --- VOD (écran 3) ----------------------------------------------------------------------------------


def radar(work: Path) -> dict[str, list[float]]:
    """Chat et volume de la VOD entière, réduits à RADAR_BINS barres entre 0 et 1."""
    path = work / "scout_signals.npz"
    if not path.exists():
        return {"chat": [], "audio": []}
    with np.load(path) as data:
        chat, loud = data["chat"], data["loudness_db"]
    n = len(loud)
    edges = np.linspace(0, n, RADAR_BINS + 1).astype(int)
    audio = np.array([loud[a:b].mean() if b > a else -90.0 for a, b in zip(edges[:-1], edges[1:], strict=True)])
    lo, hi = np.percentile(audio, 5), np.percentile(audio, 99)
    audio = np.clip((audio - lo) / max(hi - lo, 1e-6), 0, 1)
    if len(chat):
        c = np.array([chat[a:b].sum() for a, b in zip(edges[:-1], edges[1:], strict=True)])
        chat_bins = np.clip(c / max(np.percentile(c, 99), 1e-6), 0, 1)
    else:
        chat_bins = np.zeros(RADAR_BINS)
    return {"chat": [round(float(v), 3) for v in chat_bins], "audio": [round(float(v), 3) for v in audio]}


def vod_overview(vid: str) -> dict[str, Any]:
    work = WORK_DIR / vid
    scout = read_json(work / "scout.json")
    if scout is None:
        raise FileNotFoundError(f"VOD {vid} inconnue")
    brief = load_campaign(scout["campaign"])
    info = read_json(work / "info.json", {})
    fetched = read_json(work / "windows" / "windows.json", [])
    by_rank = {f["rank"]: f for f in fetched}
    windows = []
    for w in scout["windows"]:
        rank = w["rank"]
        wdir = work / "windows"
        state = "waiting"
        if rank in by_rank:
            state = "fetched"
        if (wdir / f"w_{rank:02d}.vocals.wav").exists():
            state = "audio"
        if (wdir / f"w_{rank:02d}.transcript.json").exists():
            state = "transcribed"
        windows.append({"rank": rank, "start": w["start"], "end": w["end"], "peak": w["peak"], "state": state})
    total = len(windows)
    count = {s: sum(1 for w in windows if w["state"] in s) for s in
             [("fetched", "audio", "transcribed"), ("audio", "transcribed"), ("transcribed",)]}  # fmt: skip
    candidates = read_json(work / "candidates.json")
    config = load_config()
    measured = read_json(work / "timings.json", {}).get("stages", {})
    rates = stage_rates(config.separation.enabled)
    stages: list[dict[str, Any]] = [
        {"key": "repérage", "name": "Repérage", "state": "done",
         "seconds": round(sum(scout.get("timings", {}).values()), 1),
         "steps": [{"name": k, "seconds": round(v, 1)} for k, v in scout.get("timings", {}).items()]},
        {"key": "téléchargement", "name": f"Téléchargement des {total} zones vidéo",
         "done": count[("fetched", "audio", "transcribed")], "total": total},
        {"key": "séparation", "name": "Séparation de la voix" if config.separation.enabled else "Extraction de l'audio",
         "done": count[("audio", "transcribed")], "total": total},
        {"key": "transcription", "name": f"Transcription ({config.asr.backend.capitalize()}, {brief.language.upper()})",
         "done": count[("transcribed",)], "total": total},
        {"key": "détection", "name": "Détection des moments", "done": 1 if candidates else 0, "total": 1},
    ]  # fmt: skip
    for s in stages[1:]:
        s["state"] = "done" if s["done"] >= s["total"] else ("running" if s["done"] else "waiting")
        if s["key"] in measured:
            s["seconds"] = measured[s["key"]]
        # temps restant estimé d'après les VOD déjà traitées sur cette machine (secondes par zone)
        left = total * (s["total"] - s["done"]) / s["total"]
        s["estimate_s"] = round(left * rates[s["key"]]) if s["state"] != "done" else 0
    return {
        "video_id": vid,
        "campaign": scout["campaign"],
        "campaign_name": brief.name,
        "creator": brief.creator,
        "title": scout.get("title") or info.get("title") or vid,
        "url": scout["url"],
        "platform": brief.source_platform or ("twitch" if vid.startswith("twitch-") else None),
        "language": brief.language,
        "duration": scout["duration"],
        "chat_messages": scout.get("chat_messages", 0),
        "source_rule": brief.source_rule,
        "radar": radar(work),
        "windows": windows,
        "stages": stages,
        "candidates": len(candidates["candidates"]) if candidates else 0,
        "ready_windows": count[("transcribed",)],
        "zones_seconds": round(sum(w["end"] - w["start"] for w in scout["windows"]), 1),
    }


# Secondes par zone de 75 s quand aucune VOD n'a encore été mesurée (ordres de grandeur du SPEC §10, M1-M3).
DEFAULT_RATES = {"téléchargement": 10.0, "séparation": 2.0, "transcription": 22.0, "détection": 10.0}
SEPARATION_RATE = 160.0  # RTF ≈ 2,1 (UVR-MDX-NET-Voc_FT) sur 75 s


def stage_rates(separation: bool) -> dict[str, float]:
    """Secondes par zone de chaque grande étape : médiane des zones vraiment traitées sur cette machine
    (timings.json → per_zone, sans les reprises depuis le cache), sinon valeurs par défaut."""
    rates = {**DEFAULT_RATES, "séparation": SEPARATION_RATE if separation else DEFAULT_RATES["séparation"]}
    measured: dict[str, list[float]] = {}
    for path in WORK_DIR.glob("*/timings.json"):
        for key, seconds in read_json(path, {}).get("per_zone", {}).items():
            if key in rates:
                measured.setdefault(key, []).extend(seconds)
    return {**rates, **{k: round(float(np.median(v)), 1) for k, v in measured.items()}}


def vods() -> list[dict[str, Any]]:
    """VOD repérées, la plus récente d'abord (écran VOD sans identifiant)."""
    items = []
    for path in WORK_DIR.glob("*/scout.json"):
        scout = read_json(path, {})
        items.append({"video_id": path.parent.name, "title": scout.get("title") or path.parent.name,
                      "campaign": scout.get("campaign"), "duration": scout.get("duration"),
                      "updated": path.stat().st_mtime})  # fmt: skip
    return sorted(items, key=lambda v: v["updated"], reverse=True)


# --- tri (écran 4) ----------------------------------------------------------------------------------


def window_info(vid: str) -> dict[int, dict[str, Any]]:
    return {w["rank"]: w for w in read_json(WORK_DIR / vid / "windows" / "windows.json", [])}


def moments(vid: str) -> dict[str, Any]:
    work = WORK_DIR / vid
    data = read_json(work / "candidates.json")
    if data is None:
        raise FileNotFoundError(f"aucun candidat pour {vid} : lancer l'analyse")
    edits, rerank, wins = load_edits(vid), load_rerank(vid), window_info(vid)
    best = max((c["score"] for c in data["candidates"]), default=1.0) or 1.0
    items: list[dict[str, Any]] = []
    for c in data["candidates"]:
        edit = edits.get(c["window"], {})
        llm = rerank.get(rerank_key(c))
        transcript = read_json(work / "windows" / f"w_{c['window']:02d}.transcript.json", {"words": []})
        words = corrected(transcript["words"], edit.get("corrections", {}))
        w = wins.get(c["window"], {})
        shown = apply_edit(c, edit, words, w.get("start", 0) + w.get("duration", 0)) if w else c
        score10 = round(max(0.0, c["score"]) / best * 10, 1)  # signaux, ramenés sur 10 (le meilleur = 10)
        items.append({
            "window": c["window"], "id": c["id"], "start": shown["start"], "end": shown["end"],
            "duration": shown["duration"], "peak": c["peak"], "score": score10,
            "llm_score": (llm or {}).get("score"), "reasons": c["reasons"],
            "text": shown["text"], "hook": edit.get("hook") or (llm or {}).get("hook") or "",
            "title": (llm or {}).get("title") or "", "decision": edit.get("decision"),
            "video": rel(work / c["file"]), "window_start": shown["start"] - shown["file_start"],
            "window_duration": w.get("duration"), "edited": bool(shown.get("edited")),
        })  # fmt: skip
    items.sort(key=lambda m: m["score"], reverse=True)
    kept = sum(1 for m in items if m["decision"] == "keep")
    rejected = sum(1 for m in items if m["decision"] == "reject")
    scout = read_json(work / "scout.json", {})
    brief = load_campaign(scout["campaign"]) if scout else None
    return {"video_id": vid, "moments": items, "kept": kept, "rejected": rejected,
            "remaining": len(items) - kept - rejected,
            "title": scout.get("title") or vid, "campaign": scout.get("campaign"),
            "campaign_name": brief.name if brief else "",
            "min_len": brief.clip.min_len if brief else 15.0,
            "max_len": brief.clip.max_len if brief else 59.0}  # fmt: skip


def peaks(vid: str, window: int) -> dict[str, Any]:
    """Enveloppe audio d'une plage (PEAK_POINTS valeurs 0-1) pour la forme d'onde, en cache."""
    import soundfile

    wdir = WORK_DIR / vid / "windows"
    cache = wdir / f"w_{window:02d}.peaks.json"
    if cache.exists():
        return read_json(cache)
    audio, sr = soundfile.read(str(wdir / f"w_{window:02d}.vocals.wav"), dtype="float32", always_2d=False)
    edges = np.linspace(0, len(audio), PEAK_POINTS + 1).astype(int)
    env = np.array([np.abs(audio[a:b]).max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:], strict=True)])
    env = env / max(float(env.max()), 1e-6)
    out = {"duration": len(audio) / sr, "peaks": [round(float(v), 3) for v in env]}
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def frame(vid: str, window: int) -> Path:
    """Petite image du moment (au pic) pour la liste « Ensuite » du tri, en cache à côté de la plage."""
    from qclip.utils.ffmpeg import last_line, run

    wdir = WORK_DIR / vid / "windows"
    out = wdir / f"w_{window:02d}.frame.jpg"
    if out.exists():
        return out
    m = next((x for x in moments(vid)["moments"] if x["window"] == window), None)
    if m is None:
        raise FileNotFoundError(f"moment {window} introuvable")
    t = max(0.0, m["peak"] - m["window_start"])  # temps dans le fichier de la plage
    result = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", ROOT / m["video"],
                  "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", out], timeout=60)  # fmt: skip
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"image du moment {window} impossible : {last_line(result.stderr)}")
    return out


# --- éditeur (écran 5) ------------------------------------------------------------------------------


def editor(vid: str, window: int) -> dict[str, Any]:

    work = WORK_DIR / vid
    scout = read_json(work / "scout.json", {})
    brief = load_campaign(scout["campaign"])
    config = load_config()
    m = next((x for x in moments(vid)["moments"] if x["window"] == window), None)
    if m is None:
        raise FileNotFoundError(f"moment {window} introuvable")
    edit = load_edits(vid).get(window, {})
    transcript = read_json(work / "windows" / f"w_{window:02d}.transcript.json", {"words": []})
    words = corrected(transcript["words"], edit.get("corrections", {}))
    inside = [w for w in words if m["start"] <= w["start"] and w["end"] <= m["end"]]
    probe = ffprobe(ROOT / m["video"])
    wanted = edit.get("layout") or brief.layout
    zoom = edit.get("zoom", config.render.zoom)
    # Même fonction (et même cache de facecam) que le rendu : l'aperçu montre ce que le rendu fera.
    passage = {"window": window, "start": m["start"], "file": (ROOT / m["video"]).relative_to(work).as_posix(),
               "file_start": m["start"] - m["window_start"], "duration": m["duration"]}  # fmt: skip
    layout, layout_note, facecam = clip_layout(work, passage, wanted, brief.facecam, probe.width, probe.height,
                                               config.render.fps, zoom)  # fmt: skip
    overlay = None
    if brief.overlay:
        image = ASSETS_DIR / scout["campaign"] / brief.overlay.file
        overlay = {**brief.overlay.model_dump(), "url": rel(image) if image.exists() else None}
    # m["hook"] = accroche de l'éditeur ou du rerank ; m["title"] = titre du rerank (déjà filtrés, voir moments()).
    hook = m["hook"] or make_hook(inside, m["start"], config.keywords)
    title = m["title"] or make_title(brief.creator, best_quote(inside, m["start"], config.keywords, 10), m["reasons"])
    caption = make_caption(title, brief, make_hashtags(brief))
    check = compliance(brief, m["duration"], caption, title, overlay is not None and overlay["url"] is not None)
    return {
        **m,
        "campaign": scout["campaign"],
        "words": [
            {
                "text": w["text"],
                "start": round(w["start"] - m["start"], 3),
                "end": round(w["end"] - m["start"], 3),
                "vod_start": w["start"],
                "confidence": w.get("confidence"),
                "unsure": (w.get("confidence") or 1) < LOW_CONFIDENCE,
            }
            for w in inside
        ],  # fmt: skip
        "layout": wanted,
        "style": edit.get("style") or config.subtitle.style,
        "subtitle": config.subtitle.model_dump(),
        "facecam": facecam.__dict__ if facecam else None,
        "source_size": [probe.width, probe.height],
        "overlay": overlay,
        "mention": brief.required.mention,
        "test_only": brief.test_only,
        "hook": hook,
        "hook_auto": not m["hook"],  # accroche tirée d'une citation du clip, pas choisie
        "title": title,
        "compliance": check,
        # Démonétisation sur les bornes actuelles (mots corrigés) : le risque se voit avant le rendu.
        "safety": clip_safety(
            vid,
            {"window": window, "start": m["start"], "end": m["end"]},
            words,
            config.audio_event_labels,
            brief.clip.min_len,
        ),  # fmt: skip
        "min_len": brief.clip.min_len,
        "max_len": brief.clip.max_len,
        "preview": {
            "layout": layout.name,  # layout réellement rendu (repli sur blur si la facecam n'a pas de sens)
            "note": layout_note,
            "crop": list(layout.crop) if layout.crop else None,  # layout crop : (x, largeur) de la bande 9:16
            "zoom": layout.zoom,
            "zoom_default": config.render.zoom,
            "zoom_max": MAX_ZOOM,
            "subs_y": layout.subs_y,
            "hook_y": layout.hook_y,
            "top_h": TOP_H,
            "fg_h": FG_H,
            "safe_bottom": SAFE_BOTTOM,
            "margins": [MARGIN_L, MARGIN_R],
            "hook_seconds": HOOK_SECONDS,
            "line_gap": LINE_GAP,
            "hold": HOLD,
            "watermark": WATERMARK if brief.test_only else "",
        },
        "render_estimate_s": round(m["duration"] * 0.7),  # ≈ 20 s de calcul pour un clip de 30 s (M4)
        "rendered": rendered_clip(scout["campaign"], vid, m["id"], brief.test_only),
    }


def rendered_clip(slug: str, vid: str, clip_id: int, test_only: bool) -> str | None:
    """Clip déjà rendu pour ce moment (chemin servi sous /media/), sinon None."""
    out = (WORK_DIR / vid / "renders" if test_only else ROOT / "output" / slug / vid) / f"clip_{clip_id}.mp4"
    return rel(out) if out.exists() else None


# --- pipeline (écran 6) -----------------------------------------------------------------------------


def clip_status(post: dict[str, Any], rows: list[dict[str, str]]) -> str:
    if any(float(r["paid"] or 0) > 0 for r in rows):
        return "paye"
    if any(r["post_url"] for r in rows):
        return "poste"
    safe = (post.get("safety") or {}).get("ok", True)  # clips rendus avant M6 : pas de verdict, pas de blocage
    return "rendu" if post.get("compliance", {}).get("ok") and safe else "a_revoir"


def pipeline(slug: str | None = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    slugs = [slug] if slug else campaign_slugs()
    week_ago = datetime.now(UTC) - timedelta(days=7)
    paid_week = pending = 0.0
    for s in slugs:
        brief = load_campaign(s)
        rows = read_posts(s)
        for vid in scouted(s):
            out_dir = WORK_DIR / vid / "renders" if brief.test_only else ROOT / "output" / s / vid
            for meta_path in sorted(out_dir.glob("clip_*.json")):
                if not CLIP_META_RE.fullmatch(meta_path.name):  # pas clip_3.render.json ni clip_3.safety.json
                    continue
                post = read_json(meta_path, {})
                cid = meta_path.stem.split("_")[1]
                clip_rows = [r for r in rows if r["video_id"] == vid and r["clip_id"] == cid]
                posts: dict[str, dict[str, Any]] = {
                    r["platform"]: {"url": r["post_url"], "views": int(r["views"] or 0), "paid": float(r["paid"] or 0)}
                    for r in clip_rows
                    if r["platform"]
                }
                views = sum(p["views"] for p in posts.values())
                est = sum(estimate(p["views"], brief.rate_per_1k, brief.payout_min, brief.payout_max)
                          for p in posts.values())  # fmt: skip
                paid = sum(p["paid"] for p in posts.values())
                for r in clip_rows:
                    if r["paid_at"] and datetime.fromisoformat(r["paid_at"]) >= week_ago:
                        paid_week += float(r["paid"] or 0)
                status = clip_status(post, clip_rows)
                if status == "poste":
                    pending += est
                caption_path = meta_path.with_suffix(".caption.txt")
                render_info = read_json(meta_path.with_suffix(".render.json"), {})
                items.append({
                    "window": (render_info.get("candidate") or {}).get("window"),  # pour ouvrir l'éditeur
                    "submit_within_min": brief.requirements.submit_within_min,
                    "campaign": s, "campaign_name": brief.name, "creator": brief.creator, "video_id": vid,
                    "clip_id": int(cid), "title": post.get("title", ""), "hook": post.get("hook", ""),
                    "duration": post.get("duration"), "status": status, "compliance": post.get("compliance"),
                    "safety": post.get("safety"),
                    "vod_start": (post.get("source") or {}).get("vod_start"),  # pour « décaler le début »
                    "caption": caption_path.read_text(encoding="utf-8") if caption_path.exists() else "",
                    "thumbnail": rel(meta_path.with_suffix(".jpg")), "video": rel(meta_path.with_suffix(".mp4")),
                    "posts": posts, "views": views, "estimate": round(est, 2), "paid": round(paid, 2),
                    "under_min": bool(posts) and est == 0 and views > 0, "platforms": list(brief.platforms),
                    "rendered_at": next((r["rendered_at"] for r in clip_rows if r["rendered_at"]), ""),
                    "test_only": brief.test_only,
                })  # fmt: skip
    return {"items": items, "paid_week": round(paid_week, 2), "pending": round(pending, 2)}


# --- tableau de bord (écran 1) ----------------------------------------------------------------------


def dashboard() -> dict[str, Any]:
    slugs = campaign_slugs()
    clips = pipeline()["items"]
    today = datetime.now(UTC).date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    paid_by_day = dict.fromkeys(days, 0.0)
    views_by_day = dict.fromkeys(days, 0)
    for s in slugs:
        for r in read_posts(s):
            if r["paid_at"]:
                d = datetime.fromisoformat(r["paid_at"]).date()
                if d in paid_by_day:
                    paid_by_day[d] += float(r["paid"] or 0)
            if r["post_url"] and r["logged_at"]:
                d = datetime.fromisoformat(r["logged_at"]).date()
                if d in views_by_day:
                    views_by_day[d] += int(r["views"] or 0)
    to_sort = 0
    for s in slugs:
        for vid in scouted(s):
            if (WORK_DIR / vid / "candidates.json").exists():
                to_sort += moments(vid)["remaining"]
    paid_series = [round(paid_by_day[d], 2) for d in days]
    return {
        "date": time.strftime("%Y-%m-%d"),
        "paid_7d": round(sum(paid_series), 2),
        "paid_series": paid_series,
        "paid_today": paid_series[-1],
        "paid_clips_7d": sum(1 for c in clips if c["status"] == "paye"),
        "views": sum(c["views"] for c in clips),
        "views_series": list(np.cumsum([views_by_day[d] for d in days]).tolist()),
        "to_sort": to_sort,
        "ready": sum(1 for c in clips if c["status"] == "rendu"),
        "to_check": sum(1 for c in clips if c["status"] == "a_revoir"),
        "campaigns": [campaign_summary(s) for s in slugs],
        "recent_clips": sorted(clips, key=lambda c: c["rendered_at"], reverse=True)[:6],
    }
