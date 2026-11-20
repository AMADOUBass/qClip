"""API locale de l'interface (SPEC §7) : `qclip serve`, sur localhost uniquement.

Aucune logique métier ici : chaque route appelle le cœur (campaign, edits, overview, posts, pipeline, render…).
Tâches longues dans la file `jobs` (une à la fois), suivies en direct par SSE sur /api/events.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from qclip import ROOT, overview
from qclip.campaign import ASSETS_DIR, load_campaign, save_brief
from qclip.config import ConfigError
from qclip.edits import correct_everywhere, load_edits, save_edit, word_key
from qclip.jobs import JobQueue
from qclip.posts import log_post
from qclip.sources import WORK_DIR, twitch_vod_id

MEDIA_ROOTS = [ROOT / "work", ROOT / "output", ASSETS_DIR]
VID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class BriefBody(BaseModel):
    slug: str | None = None
    brief: dict[str, Any]


class VodBody(BaseModel):
    url: str


class EditBody(BaseModel):
    decision: str | None = None
    start: float | None = None
    end: float | None = None
    layout: str | None = None
    style: str | None = None
    hook: str | None = None


class CorrectionBody(BaseModel):
    text: str
    start: float | None = None  # début (temps VOD) du mot à corriger
    old: str | None = None  # ou : corriger toutes les occurrences de ce mot


class RenderBody(BaseModel):
    windows: list[int] | None = None
    kept: bool = False


class LogBody(BaseModel):
    platform: str
    url: str | None = None
    views: int | None = None
    paid: float | None = None


def check_vid(vid: str) -> str:
    if not VID_RE.match(vid) or not (WORK_DIR / vid / "scout.json").exists():
        raise HTTPException(404, f"VOD {vid} inconnue")
    return vid


def campaign_of(vid: str) -> str:
    return json.loads((WORK_DIR / vid / "scout.json").read_text(encoding="utf-8"))["campaign"]


def create_app(queue: JobQueue | None = None) -> FastAPI:
    app = FastAPI(title="qClip", version="0.1.0")
    jobs = queue or JobQueue()
    app.state.jobs = jobs
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ConfigError)
    @app.exception_handler(ValueError)
    async def bad_request(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def not_found(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(RuntimeError)
    async def conflict(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # --- lecture -----------------------------------------------------------------------------------

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        current = jobs.current()
        return {**overview.system_status(), "job": current.to_dict() if current else None}

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        current = jobs.current()
        return {**overview.dashboard(), "job": current.to_dict() if current else None}

    @app.get("/api/campaigns")
    def campaigns() -> list[dict[str, Any]]:
        return overview.dashboard()["campaigns"]

    @app.get("/api/campaigns/{slug}")
    def campaign(slug: str) -> dict[str, Any]:
        return {**overview.brief_view(slug), "summary": overview.campaign_summary(slug)}

    @app.get("/api/vods")
    def vod_list() -> list[dict[str, Any]]:
        return overview.vods()

    @app.get("/api/vods/{vid}")
    def vod(vid: str) -> dict[str, Any]:
        return overview.vod_overview(check_vid(vid))

    @app.get("/api/vods/{vid}/moments")
    def moments(vid: str) -> dict[str, Any]:
        return overview.moments(check_vid(vid))

    @app.get("/api/vods/{vid}/moments/{window}/peaks")
    def peaks(vid: str, window: int) -> dict[str, Any]:
        return overview.peaks(check_vid(vid), window)

    @app.get("/api/vods/{vid}/moments/{window}/editor")
    def editor(vid: str, window: int) -> dict[str, Any]:
        return overview.editor(check_vid(vid), window)

    @app.get("/api/clips")
    def clips(campaign: str | None = None) -> dict[str, Any]:
        return overview.pipeline(campaign)

    @app.get("/api/jobs")
    def job_list() -> list[dict[str, Any]]:
        return [j.to_dict() for j in jobs.all()]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: int) -> dict[str, Any]:
        found = jobs.get(job_id)
        if found is None:
            raise HTTPException(404, "tâche inconnue")
        return found.to_dict()

    @app.get("/api/events", response_class=EventSourceResponse)
    async def events() -> AsyncIterator[ServerSentEvent]:
        """Pousse l'état des tâches à chaque changement (et un battement toutes les 15 s)."""
        seen = -1
        while True:
            version = await asyncio.to_thread(jobs.wait_change, seen, 15.0)
            if version == seen:
                yield ServerSentEvent(comment="ping")
                continue
            seen = version
            yield ServerSentEvent(data={"version": version, "jobs": [j.to_dict() for j in jobs.all()[:20]]},
                                  event="jobs")  # fmt: skip

    @app.get("/media/{path:path}")
    def media(path: str) -> FileResponse:
        target = (ROOT / path).resolve()
        if not any(target.is_relative_to(root.resolve()) for root in MEDIA_ROOTS) or not target.is_file():
            raise HTTPException(404, "fichier introuvable")
        return FileResponse(target, content_disposition_type="inline")

    # --- écriture ----------------------------------------------------------------------------------

    @app.post("/api/campaigns", status_code=201)
    def create_campaign(body: BriefBody) -> dict[str, Any]:
        if not body.slug:
            raise ConfigError("slug obligatoire")
        save_brief(body.slug, body.brief, create=True)
        return overview.brief_view(body.slug)

    @app.put("/api/campaigns/{slug}")
    def update_campaign(slug: str, body: BriefBody) -> dict[str, Any]:
        save_brief(slug, body.brief)
        return overview.brief_view(slug)

    @app.post("/api/campaigns/{slug}/overlay")
    async def upload_overlay(slug: str, file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        brief = load_campaign(slug)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename or "overlay.png").name)
        if not name.lower().endswith((".png", ".webp")):
            raise ConfigError("overlay : image PNG ou WebP attendue (avec transparence)")
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise ConfigError("overlay : 10 Mo maximum")
        target = ASSETS_DIR / slug / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        current = brief.model_dump(mode="json")
        current["overlay"] = {**(current.get("overlay") or {}), "file": name}
        save_brief(slug, current)
        return overview.brief_view(slug)

    @app.post("/api/campaigns/{slug}/vods", status_code=202)
    def add_vod(slug: str, body: VodBody) -> dict[str, Any]:
        """Ajoute l'URL aux sources du brief (c'est l'autorisation de la campagne) puis lance l'analyse."""
        from qclip.pipeline import process_vod

        brief = load_campaign(slug)
        if body.url not in brief.sources:
            data = brief.model_dump(mode="json")
            data["sources"] = [*brief.sources, body.url]
            save_brief(slug, data)
        vod = twitch_vod_id(body.url)  # connu sans réseau pour Twitch : l'écran VOD peut s'ouvrir tout de suite
        job = jobs.submit("process", f"Analyse de {body.url}", slug, lambda steps: process_vod(slug, body.url, steps),
                          video_id=f"twitch-{vod}" if vod else None)  # fmt: skip
        return {"job": job.to_dict(), "source_rule": brief.source_rule}

    @app.put("/api/vods/{vid}/moments/{window}")
    def edit_moment(vid: str, window: int, body: EditBody) -> dict[str, Any]:
        check_vid(vid)
        changes = body.model_dump(exclude_unset=True)  # null explicite = retour au réglage par défaut
        if not changes:
            raise ConfigError("aucun réglage à enregistrer")
        return {"window": window, "edit": save_edit(vid, window, **changes)}

    @app.post("/api/vods/{vid}/moments/{window}/corrections")
    def correct(vid: str, window: int, body: CorrectionBody) -> dict[str, Any]:
        check_vid(vid)
        transcript = WORK_DIR / vid / "windows" / f"w_{window:02d}.transcript.json"
        words = json.loads(transcript.read_text(encoding="utf-8"))["words"]
        current = dict(load_edits(vid).get(window, {}).get("corrections", {}))
        if body.old:
            fixes = correct_everywhere(words, body.old, body.text)
            if not fixes:
                raise ConfigError(f"« {body.old} » introuvable dans ce moment")
            current.update(fixes)
        elif body.start is not None:
            current[word_key(body.start)] = body.text.strip()
        else:
            raise ConfigError("donner `start` (un mot) ou `old` (toutes les occurrences)")
        save_edit(vid, window, corrections=current)
        return overview.editor(vid, window)

    @app.post("/api/vods/{vid}/render", status_code=202)
    def render(vid: str, body: RenderBody) -> dict[str, Any]:
        from qclip.render import render_candidates

        check_vid(vid)
        slug = campaign_of(vid)
        ids = None
        if body.windows:
            data = json.loads((WORK_DIR / vid / "candidates.json").read_text(encoding="utf-8"))
            ids = [c["id"] for c in data["candidates"] if c["window"] in body.windows]
            if not ids:
                raise ConfigError("aucun moment à rendre")
        label = f"Rendu de {len(ids)} clip(s)" if ids else "Rendu des moments gardés"
        job = jobs.submit("render", label, slug, video_id=vid,
                          fn=lambda steps: [str(r["path"]) for r in render_candidates(
                              slug, vid, ids, None, steps, force=True, kept_only=body.kept and not ids)])  # fmt: skip
        return {"job": job.to_dict()}

    @app.post("/api/clips/{slug}/{vid}/{clip_id}/log")
    def log(slug: str, vid: str, clip_id: int, body: LogBody) -> dict[str, Any]:
        check_vid(vid)
        row = log_post(slug, f"{vid}/{clip_id}", body.platform, body.url, body.views, body.paid)
        return {"row": row}

    return app


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("qclip serve n'écoute que sur la machine locale (127.0.0.1)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
