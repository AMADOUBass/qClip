"""Rendu d'un candidat en clip vertical 1080x1920 (SPEC §4.8) : layout, sous-titres, accroche, loudnorm, encodage.

Un clip = un seul passage ffmpeg (vidéo + sous-titres + audio normalisé), après une passe de mesure du volume.
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from qclip import ROOT
from qclip.facecam import Facecam
from qclip.meta import make_hook
from qclip.rerank import key as rerank_key
from qclip.rerank import load_rerank, ordered
from qclip.subtitles import HEIGHT, SAFE_BOTTOM, WIDTH, TimedWord, build_ass, save_ass
from qclip.utils.ffmpeg import last_line, run, try_encode

FONTS_DIR = ROOT / "assets" / "fonts"
TOP_H = 640  # layout facecam : zone webcam en haut (1080 x 640), jeu en bas (1080 x 1280)
FG_H = round(WIDTH * 9 / 16)  # layout blur : image 16:9 au centre (1080 x 608)
LUFS_TP, LUFS_LRA = -1.5, 11.0
WATERMARK = "TEST — NE PAS POSTER"
MAX_ZOOM = 1.10  # variation anti-doublon : au-delà, on perd trop de bord d'image


@dataclass
class Layout:
    name: str  # facecam | blur | crop
    filter: str  # graphe ffmpeg : [0:v] → [v]
    subs_y: int  # centre vertical des sous-titres
    hook_y: int  # centre vertical de l'accroche
    crop: tuple[int, int] | None = None  # layout crop : (x, largeur) de la bande 9:16 prise dans la source
    zoom: float = 1.0  # variation anti-doublon (agrandissement centré, après le layout)


def blur_layout(fps: int) -> Layout:
    fg_top = (HEIGHT - FG_H) // 2
    # Le fond flou est calculé en petit (270x480) puis agrandi : même rendu, 16 fois moins de pixels à flouter.
    graph = (
        f"[0:v]fps={fps},split=2[a][b];"
        "[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,gblur=sigma=12,"
        f"scale={WIDTH}:{HEIGHT},eq=brightness=-0.08[bg];"
        f"[b]scale={WIDTH}:-2[fg];[bg][fg]overlay=0:{fg_top}[v]"
    )
    below_fg = fg_top + FG_H
    return Layout("blur", graph, subs_y=(below_fg + SAFE_BOTTOM) // 2, hook_y=fg_top // 2 + 60)


def facecam_layout(fps: int, rect: list[int], src_w: int, src_h: int) -> Layout:
    x, y, w, h = rect
    game_h = HEIGHT - TOP_H
    # Jeu : bande centrale de la source, au format de la zone du bas (1080 x 1280).
    gw = min(src_w, round(src_h * WIDTH / game_h))
    gx = (src_w - gw) // 2
    graph = (
        f"[0:v]fps={fps},split=2[a][b];"
        f"[a]crop={w}:{h}:{x}:{y},scale={WIDTH}:{TOP_H}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{TOP_H}[top];"
        f"[b]crop={gw}:{src_h}:{gx}:0,scale={WIDTH}:{game_h}[game];"
        "[top][game]vstack=inputs=2[v]"
    )
    # Sous-titres dans le jeu, au-dessus de la zone interdite du bas ; jamais sur la webcam.
    return Layout("facecam", graph, subs_y=TOP_H + (SAFE_BOTTOM - TOP_H) * 2 // 3, hook_y=TOP_H + 90)


def crop_layout(fps: int, face: list[int] | None, src_w: int, src_h: int) -> Layout:
    """Recadrage : bande 9:16 de toute la hauteur de la source, centrée sur le visage (caméra plein cadre)
    ou au centre de l'image, agrandie en 1080 x 1920."""
    width = min(src_w, round(src_h * WIDTH / HEIGHT))
    width -= width % 2
    center = face[0] + face[2] / 2 if face else src_w / 2
    x = int(min(max(center - width / 2, 0), src_w - width))
    graph = f"[0:v]fps={fps},crop={width}:{src_h}:{x}:0,scale={WIDTH}:{HEIGHT}[v]"
    blur = blur_layout(fps)  # mêmes positions de texte : sous-titres au-dessus de la zone interdite, accroche en haut
    return Layout("crop", graph, subs_y=blur.subs_y, hook_y=blur.hook_y, crop=(x, width))


def choose_layout(wanted: str, facecam: Facecam | None, fps: int, src_w: int, src_h: int) -> tuple[Layout, str | None]:
    """Layout du brief, ou repli sur blur (avec la raison) si la facecam n'a pas de sens pour cette VOD."""
    if wanted == "facecam":
        if facecam and facecam.rect:
            return facecam_layout(fps, facecam.rect, src_w, src_h), None
        reason = "caméra plein cadre (pas de webcam incrustée)" if facecam and facecam.mode == "fullcam" else (
            "aucune webcam détectée")  # fmt: skip
        return blur_layout(fps), f"layout facecam impossible ({reason}) : repli sur blur"
    if wanted == "crop":
        # Centré sur le visage seulement s'il occupe l'image (fullcam) ; une webcam dans un coin n'est pas le sujet.
        face = facecam.face if facecam and facecam.mode == "fullcam" else None
        return crop_layout(fps, face, src_w, src_h), None
    return blur_layout(fps), None


def with_zoom(layout: Layout, zoom: float) -> Layout:
    """Variation anti-doublon : image agrandie de `zoom` (1,00-1,10) et recadrée au centre, avant le texte.
    Sous-titres, accroche et overlay restent nets et à leur place (ils sont ajoutés après)."""
    if not 1.0 <= zoom <= MAX_ZOOM:
        raise ValueError(f"zoom {zoom} hors de [1, {MAX_ZOOM}]")
    if zoom == 1.0:
        return layout
    if not layout.filter.endswith("[v]"):
        raise ValueError("graphe de layout inattendu (doit finir par [v])")
    w, h = round(WIDTH * zoom / 2) * 2, round(HEIGHT * zoom / 2) * 2
    graph = f"{layout.filter[:-3]}[pre];[pre]scale={w}:{h},crop={WIDTH}:{HEIGHT}[v]"
    return Layout(layout.name, graph, layout.subs_y, layout.hook_y, layout.crop, zoom)


def clip_layout(
    work: Path,
    c: dict[str, Any],
    wanted: str,
    brief_facecam: list[int] | None,
    src_w: int,
    src_h: int,
    fps: int,
    zoom: float,
    force: bool = False,
) -> tuple[Layout, str | None, Facecam | None]:
    """Layout réellement rendu pour un passage (`c` : window, start, file, file_start, duration), zoom compris.
    Partagé par le rendu et l'aperçu de l'éditeur : les deux ne peuvent pas diverger."""
    facecam: Facecam | None = None
    if wanted in ("facecam", "crop"):
        if brief_facecam:
            facecam = Facecam("overlay", None, brief_facecam, "brief")
        else:  # la scène change pendant un live : la facecam se cherche dans chaque clip
            from qclip.facecam import detect_for_clip

            cache = work / "facecam" / f"w{c['window']:02d}_{c['start']:.1f}.json"  # dépend du passage
            facecam = detect_for_clip(work / c["file"], c["file_start"], c["duration"], src_w, src_h, cache, force)
    layout, warning = choose_layout(wanted, facecam, fps, src_w, src_h)
    return with_zoom(layout, zoom), warning, facecam


def measure_loudness(video: Path, start: float, duration: float) -> dict[str, str]:
    """Passe 1 de loudnorm : mesures du passage (JSON imprimé par ffmpeg sur stderr)."""
    result = run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video, "-vn",
         "-af", f"loudnorm=I=-14:TP={LUFS_TP}:LRA={LUFS_LRA}:print_format=json", "-f", "null", "-"],
        timeout=300,
    )  # fmt: skip
    found = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr)
    if result.returncode != 0 or not found:
        raise RuntimeError(f"mesure loudnorm impossible : {last_line(result.stderr)}")
    return json.loads(found.group(0))


def loudnorm_filter(m: dict[str, str], lufs: float) -> str:
    return (
        f"loudnorm=I={lufs}:TP={LUFS_TP}:LRA={LUFS_LRA}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
        "linear=true,aresample=48000"
    )


_ENCODER: str | None = None


def pick_encoder(wanted: str) -> str:
    """`auto` : h264_qsv s'il encode vraiment (testé une fois), sinon libx264."""
    global _ENCODER
    if wanted != "auto":
        return wanted
    if _ENCODER is None:
        _ENCODER = "h264_qsv" if try_encode("h264_qsv")[0] else "libx264"
    return _ENCODER


def encoder_args(encoder: str) -> list[str]:
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "23", "-look_ahead", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def render_clip(
    candidate: dict[str, Any],
    work: Path,
    out_path: Path,
    layout: Layout,
    words: list[dict[str, Any]],
    subtitle_style: Any,
    lufs: float,
    encoder: str,
    hook: str,
    mention: str,
    test_only: bool,
    overlay: tuple[Path, Any] | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    """Rend un candidat. Écrit clip.mp4 + clip.ass + clip.words.tsv (mots affichés, pour contrôle).

    `words` arrive déjà corrigé par l'éditeur (seule source des corrections depuis M8 ; clip.words.tsv est régénéré).
    `overlay` = (image, Overlay du brief) incrustée sous les sous-titres ; `variant` = style des sous-titres."""
    video = work / candidate["file"]
    start, duration = candidate["file_start"], candidate["duration"]
    words_tsv = out_path.with_suffix(".words.tsv")
    span = (candidate["start"], candidate["end"])
    inside = [w for w in words if span[0] <= w["start"] and w["end"] <= span[1]]
    timed = [TimedWord(w["text"], round(w["start"] - span[0], 3), round(w["end"] - span[0], 3)) for w in inside]
    save_words_tsv(timed, words_tsv, span)
    ass = save_ass(
        build_ass(timed, subtitle_style, layout.subs_y, duration, hook=hook, hook_y=layout.hook_y, mention=mention,
                  watermark=WATERMARK if test_only else "", variant=variant),
        out_path.with_suffix(".ass"),
    )  # fmt: skip
    loud = measure_loudness(video, start, duration)
    # Chemins relatifs + cwd = racine du projet : pas d'échappement de « C:\ » dans la syntaxe des filtres.
    ass_rel = ass.relative_to(ROOT).as_posix()
    fonts_rel = FONTS_DIR.relative_to(ROOT).as_posix()
    inputs: list[str | Path] = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video]
    if overlay:
        # Overlay du brief (image fixe) incrusté sous les sous-titres : jamais caché par eux.
        image, spec = overlay
        inputs += ["-i", image]
        x, y, w = round(spec.x * WIDTH), round(spec.y * HEIGHT), round(spec.width * WIDTH)
        graph = (f"{layout.filter};[1:v]scale={w}:-1[ov];[v][ov]overlay={x}:{y}[vo];"
                 f"[vo]subtitles={ass_rel}:fontsdir={fonts_rel}[out]")  # fmt: skip
    else:
        graph = f"{layout.filter};[v]subtitles={ass_rel}:fontsdir={fonts_rel}[out]"
    result = run(
        ["ffmpeg", "-y", "-hide_banner", "-v", "error", *inputs,
         "-filter_complex", graph, "-map", "[out]", "-map", "0:a:0", *encoder_args(encoder),
         "-af", loudnorm_filter(loud, lufs), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", out_path],
        timeout=1800,
        cwd=ROOT,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"rendu impossible ({encoder}) : {last_line(result.stderr)}")
    return {"input_lufs": float(loud["input_i"]), "words": len(timed), "ass": ass.name, "words_tsv": words_tsv.name,
            "overlay": bool(overlay), "style": variant or subtitle_style.style}  # fmt: skip


def save_words_tsv(words: list[TimedWord], path: Path, span: tuple[float, float]) -> None:
    lines = [
        f"# passage {span[0]:.3f} {span[1]:.3f}   (temps VOD)",
        "# début\tfin\ttexte   (fichier GÉNÉRÉ à chaque rendu : corriger les mots dans l'éditeur de l'interface)",
    ]
    lines += [f"{w.start:.3f}\t{w.end:.3f}\t{w.text}" for w in words]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_candidates(
    slug: str,
    vid: str,
    ids: list[int] | None,
    top: int | None,
    steps: Any,
    layout_name: str | None = None,
    hook: str | None = None,
    force: bool = False,
    kept_only: bool = False,
) -> list[dict[str, Any]]:
    """Rend les candidats choisis → output/<campagne>/<id>/ (ou work/<id>/renders/ si test_only).

    Choix : `ids`, sinon les moments gardés au tri (`kept_only`), sinon les N meilleurs non rejetés.
    Réglages de l'éditeur (edits.json) appliqués : bornes, layout, style, accroche, corrections de mots."""
    from qclip.campaign import ASSETS_DIR, load_campaign
    from qclip.config import load_config
    from qclip.edits import apply_edit, corrected, load_edits
    from qclip.ingest import load_fetched
    from qclip.sources import WORK_DIR
    from qclip.transcribe import transcript_path
    from qclip.utils.ffmpeg import ffprobe

    config, brief = load_config(), load_campaign(slug)
    work = WORK_DIR / vid
    data = json.loads((work / "candidates.json").read_text(encoding="utf-8"))
    rerank = load_rerank(vid)
    edits = load_edits(vid)
    limit = top or config.clips.top_n
    # Sans --ids : les moments gardés au tri, ou les N meilleurs (LLM s'il y a un rerank, sinon signaux) non rejetés.
    if ids:
        chosen = [c for c in data["candidates"] if c["id"] in ids]
    elif kept_only:
        chosen = [c for c in data["candidates"] if edits.get(c["window"], {}).get("decision") == "keep"]
        if not chosen:
            raise RuntimeError("aucun moment gardé : trier d'abord les moments")
    else:
        pool = [c for c in data["candidates"] if edits.get(c["window"], {}).get("decision") != "reject"]
        chosen = ordered(pool, rerank)[:limit]
    if ids and len(chosen) != len(ids):
        raise RuntimeError(f"candidats introuvables : {sorted(set(ids) - {c['id'] for c in chosen})}")
    if hook and len(chosen) != 1:
        raise RuntimeError("--hook ne s'utilise qu'avec un seul clip (--ids N)")
    out_dir = work / "renders" if brief.test_only else ROOT / "output" / slug / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    if brief.test_only:
        steps.info(f"campagne de test : rendus dans {out_dir.relative_to(ROOT)} avec le bandeau « {WATERMARK} »")

    windows = load_fetched(vid)
    window_end = {w["rank"]: w["start"] + w["duration"] for w in windows}
    probe = ffprobe(work / "windows" / windows[0]["file"])
    encoder = pick_encoder(config.render.encoder)
    mention = brief.required.mention
    overlay = None
    if brief.overlay:
        image = ASSETS_DIR / slug / brief.overlay.file
        if not image.exists():
            raise RuntimeError(f"overlay obligatoire introuvable : {image} (l'ajouter depuis le brief)")
        overlay = (image, brief.overlay)

    results = []
    for c in chosen:
        out_path = out_dir / f"clip_{c['id']}.mp4"
        if out_path.exists() and not force:
            steps.info(f"clip_{c['id']}.mp4 existe déjà (--force pour refaire)")
            continue
        edit = edits.get(c["window"], {})
        all_words = json.loads(transcript_path(work / "windows", c["window"]).read_text(encoding="utf-8"))["words"]
        words = corrected(all_words, edit.get("corrections", {}))
        c = apply_edit(c, edit, words, window_end[c["window"]])
        wanted = layout_name or edit.get("layout") or brief.layout
        layout, warning, facecam = clip_layout(
            work, c, wanted, brief.facecam, probe.width, probe.height, config.render.fps,
            edit.get("zoom", config.render.zoom), force,
        )  # fmt: skip
        if warning:
            steps.info(f"clip {c['id']} : {warning}")
        inside = [w for w in words if c["start"] <= w["start"] and w["end"] <= c["end"]]
        llm = rerank.get(rerank_key(c), {})
        clip_hook = hook if hook is not None else (
            edit.get("hook") or llm.get("hook")
            or make_hook(inside, c["start"], config.keywords_for(brief.language), brief.language))  # fmt: skip
        with steps.step(f"clip {c['id']} ({c['duration']:.0f} s, {layout.name}, {encoder})"):
            info = render_clip(c, work, out_path, layout, words, config.subtitle, config.render.lufs, encoder,
                               clip_hook, mention, brief.test_only, overlay, edit.get("style"))  # fmt: skip
        meta = {"candidate": c, "layout": layout.name, "zoom": layout.zoom,
                "facecam": asdict(facecam) if facecam else None, "encoder": encoder, "hook": clip_hook,
                "layout_filter": layout.filter, **info}  # fmt: skip
        out_path.with_suffix(".render.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        with steps.step(f"meta clip {c['id']} (titre, légende, miniature)"):
            post = write_meta(slug, vid, c, out_path, inside, llm)
        steps.info(f"{out_path.relative_to(ROOT)} — accroche « {clip_hook} » — titre « {post['title']} »"
                   + ("" if post["compliance"]["ok"] else " — ⚠️ brief non respecté"))  # fmt: skip
        results.append({"path": out_path, **meta, "post": post})
    return results


def clip_safety(
    vid: str,
    c: dict[str, Any],
    words: list[dict[str, Any]],
    labels: list[str],
    min_len: float,
    clip: Path | None = None,
    thumbnail: Path | None = None,
    vision_model: str | None = None,
    lang: str = "fr",
) -> dict:
    """Verdict démonétisation : gros mots (langue du clip) et sons violents dans les 7 premières secondes,
    + images si vision activée."""
    from qclip.safety import check, window_events
    from qclip.sources import WORK_DIR

    found = window_events(WORK_DIR / vid / "windows", c["window"], words, labels, lang)
    verdict = check(c["start"], c["end"], found, min_len)
    if clip is not None and vision_model:
        from qclip.vision import check_images

        try:
            vision = check_images(clip, thumbnail, vision_model)
        except RuntimeError as e:  # Ollama arrêté, modèle absent… : le verdict son + mots reste valable
            verdict["vision"] = {"error": str(e)}
            return verdict
        verdict["vision"] = vision
        if vision["flagged"]:
            # Un drapeau lisible comme les autres (pipeline, éditeur, CLI). Les images ne datent l'évènement qu'à
            # la seconde près : pas de décalage automatique, le début se règle à l'œil dans l'éditeur.
            verdict["ok"] = False
            verdict["flags"].append(
                {"kind": "image", "at": (vision["at"] or [0.0])[0], "detail": vision["description"]}
            )
            verdict["shift_s"] = None
    return verdict


def write_meta(
    slug: str, vid: str, c: dict[str, Any], clip: Path, words: list[dict[str, Any]], llm: dict[str, Any]
) -> dict[str, Any]:
    """clip_<n>.json + clip_<n>.caption.txt + clip_<n>.jpg à côté du clip, et sa ligne dans posts.csv."""
    from qclip.campaign import load_campaign
    from qclip.config import load_config
    from qclip.meta import best_quote, compliance, make_caption, make_hashtags, make_title, sharpest_time
    from qclip.posts import record_render
    from qclip.sources import WORK_DIR
    from qclip.utils.ffmpeg import media_duration

    config, brief = load_config(), load_campaign(slug)
    lang = brief.language
    quote = best_quote(words, c["start"], config.keywords_for(lang), 10, lang=lang)
    title = llm.get("title") or make_title(brief.creator, quote, c["reasons"], lang)
    hashtags = make_hashtags(brief)
    caption = make_caption(title, brief, hashtags)
    duration = media_duration(clip)
    render_info = json.loads(clip.with_suffix(".render.json").read_text(encoding="utf-8"))
    # Miniature PROPRE : image de la source passée par le même layout, sans sous-titres ni accroche ;
    # netteté mesurée sur la source (le texte incrusté fausserait la mesure).
    if "layout_filter" not in render_info:
        raise RuntimeError(f"{clip.name} a été rendu avant M5 : le refaire avec `qclip render --ids {c['id']} --force`")
    source = WORK_DIR / vid / c["file"]
    peak_file = c["file_start"] + (c["peak"] - c["start"])
    t_file = sharpest_time(source, peak_file, c["file_start"] + duration)
    t_file = min(max(t_file, c["file_start"] + 0.2), c["file_start"] + duration - 0.2)
    thumb = clip.with_suffix(".jpg")
    result = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t_file:.2f}", "-i", source,
                  "-filter_complex", render_info["layout_filter"], "-map", "[v]", "-frames:v", "1", "-q:v", "2",
                  thumb], timeout=60)  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"miniature impossible : {last_line(result.stderr)}")
    thumb_t = t_file - c["file_start"]
    post = {
        "title": title,
        "hook": render_info.get("hook", ""),
        "hashtags": hashtags,
        "mention": brief.required.mention,
        "caption_file": clip.with_suffix(".caption.txt").name,
        "thumbnail": thumb.name,
        "thumbnail_time": round(thumb_t, 2),
        "platforms": list(brief.platforms),
        "duration": round(duration, 2),
        "source": {"video_id": vid, "vod_start": c["start"], "vod_end": c["end"]},
        "llm": llm or None,
        "test_only": brief.test_only,
        "compliance": compliance(brief, duration, caption, title, render_info.get("overlay", False)),
        "safety": clip_safety(
            vid,
            c,
            words,
            config.audio_event_labels,
            brief.clip.min_len,
            clip=clip if config.llm.use_vision else None,
            thumbnail=thumb if config.llm.use_vision else None,
            vision_model=config.llm.vision_model if config.llm.use_vision else None,
            lang=lang,
        ),
    }
    clip.with_suffix(".safety.json").write_text(json.dumps(post["safety"], ensure_ascii=False, indent=2), "utf-8")
    clip.with_suffix(".caption.txt").write_text(caption, encoding="utf-8")
    clip.with_suffix(".json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    sources = json.loads((ROOT / "input" / slug / "sources.json").read_text(encoding="utf-8"))
    url = next((s["url"] for s in sources if s["video_id"] == vid), "")
    record_render(slug, {"video_id": vid, "clip_id": c["id"], "vod_start": c["start"], "vod_end": c["end"],
                         "duration": round(duration, 2), "title": title, "clip_file": str(clip.relative_to(ROOT)),
                         "source_url": url})  # fmt: skip
    return post
