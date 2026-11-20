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
from qclip.subtitles import HEIGHT, HOOK_SECONDS, SAFE_BOTTOM, WIDTH, TimedWord, build_ass, save_ass
from qclip.utils.ffmpeg import last_line, run, try_encode

FONTS_DIR = ROOT / "assets" / "fonts"
TOP_H = 640  # layout facecam : zone webcam en haut (1080 x 640), jeu en bas (1080 x 1280)
FG_H = round(WIDTH * 9 / 16)  # layout blur : image 16:9 au centre (1080 x 608)
LUFS_TP, LUFS_LRA = -1.5, 11.0
WATERMARK = "TEST — NE PAS POSTER"


@dataclass
class Layout:
    name: str  # facecam | blur
    filter: str  # graphe ffmpeg : [0:v] → [v]
    subs_y: int  # centre vertical des sous-titres
    hook_y: int  # centre vertical de l'accroche


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


def choose_layout(wanted: str, facecam: Facecam | None, fps: int, src_w: int, src_h: int) -> tuple[Layout, str | None]:
    """Layout du brief, ou repli sur blur (avec la raison) si la facecam n'a pas de sens pour cette VOD."""
    if wanted == "facecam":
        if facecam and facecam.rect:
            return facecam_layout(fps, facecam.rect, src_w, src_h), None
        reason = "caméra plein cadre (pas de webcam incrustée)" if facecam and facecam.mode == "fullcam" else (
            "aucune webcam détectée")  # fmt: skip
        return blur_layout(fps), f"layout facecam impossible ({reason}) : repli sur blur"
    if wanted == "crop":
        return blur_layout(fps), "layout crop prévu au jalon M6 : repli sur blur"
    return blur_layout(fps), None


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


def default_hook(words: list[dict[str, Any]], clip_start: float) -> str:
    """Accroche provisoire (en attendant le LLM / les gabarits de M5) : une phrase courte et vive du clip,
    prononcée APRÈS les 3 premières secondes (sinon l'accroche doublerait le sous-titre affiché au même moment)."""
    sentences: list[tuple[float, str]] = []
    current: list[str] = []
    first = 0.0
    for w in words:
        if not current:
            first = w["start"] - clip_start
        current.append(w["text"])
        if w["text"].rstrip().endswith((".", "?", "!", "…")):
            sentences.append((first, " ".join(current)))
            current = []
    if current:
        sentences.append((first, " ".join(current)))
    later = [s for t, s in sentences if t >= HOOK_SECONDS and 2 <= len(s.split()) <= 8]
    lively = [s for s in later if s.rstrip().endswith(("?", "!"))]
    return (lively or later or [""])[0].rstrip(".…")


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
) -> dict[str, Any]:
    """Rend un candidat. Écrit clip.mp4 + clip.ass + clip.words.tsv (texte corrigeable à la main)."""
    video = work / candidate["file"]
    start, duration = candidate["file_start"], candidate["duration"]
    words_tsv = out_path.with_suffix(".words.tsv")
    span = (candidate["start"], candidate["end"])
    timed = load_words_tsv(words_tsv, span) if words_tsv.exists() else None
    if timed is None:
        if words_tsv.exists():  # passage modifié (nouveaux réglages) : les temps ne valent plus, on garde l'ancien
            words_tsv.replace(words_tsv.with_suffix(".tsv.old"))
        timed = [
            TimedWord(w["text"], round(w["start"] - span[0], 3), round(w["end"] - span[0], 3))
            for w in words if span[0] <= w["start"] and w["end"] <= span[1]
        ]  # fmt: skip
    save_words_tsv(timed, words_tsv, span)
    ass = save_ass(
        build_ass(timed, subtitle_style, layout.subs_y, duration, hook=hook, hook_y=layout.hook_y, mention=mention,
                  watermark=WATERMARK if test_only else ""),
        out_path.with_suffix(".ass"),
    )  # fmt: skip
    loud = measure_loudness(video, start, duration)
    # Chemins relatifs + cwd = racine du projet : pas d'échappement de « C:\ » dans la syntaxe des filtres.
    ass_rel = ass.relative_to(ROOT).as_posix()
    fonts_rel = FONTS_DIR.relative_to(ROOT).as_posix()
    graph = f"{layout.filter};[v]subtitles={ass_rel}:fontsdir={fonts_rel}[out]"
    result = run(
        ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", video,
         "-filter_complex", graph, "-map", "[out]", "-map", "0:a:0", *encoder_args(encoder),
         "-af", loudnorm_filter(loud, lufs), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", out_path],
        timeout=1800,
        cwd=ROOT,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"rendu impossible ({encoder}) : {last_line(result.stderr)}")
    return {"input_lufs": float(loud["input_i"]), "words": len(timed), "ass": ass.name, "words_tsv": words_tsv.name}


def save_words_tsv(words: list[TimedWord], path: Path, span: tuple[float, float]) -> None:
    lines = [
        f"# passage {span[0]:.3f} {span[1]:.3f}   (temps VOD ; ne pas modifier cette ligne)",
        "# début\tfin\ttexte   (secondes depuis le début du clip ; corriger la 3e colonne puis relancer le rendu)",
    ]
    lines += [f"{w.start:.3f}\t{w.end:.3f}\t{w.text}" for w in words]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_words_tsv(path: Path, span: tuple[float, float]) -> list[TimedWord] | None:
    """Mots (éventuellement corrigés à la main) du clip, ou None si le fichier décrit un autre passage."""
    words = []
    same_span = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# passage "):
            start, end = (float(v) for v in line.split()[2:4])
            same_span = abs(start - span[0]) < 0.001 and abs(end - span[1]) < 0.001
            continue
        if not line.strip() or line.startswith("#"):
            continue
        start_s, end_s, text = line.split("\t", 2)
        if text.strip():
            words.append(TimedWord(text.strip(), float(start_s), float(end_s)))
    return words if same_span else None


def render_candidates(
    slug: str,
    vid: str,
    ids: list[int] | None,
    top: int | None,
    steps: Any,
    layout_name: str | None = None,
    hook: str | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Rend les candidats choisis (ids ou top N) → output/<campagne>/<id>/ (ou work/<id>/renders/ si test_only)."""
    from qclip.campaign import load_campaign
    from qclip.config import load_config
    from qclip.facecam import Facecam, detect_for_clip
    from qclip.ingest import load_fetched
    from qclip.sources import WORK_DIR
    from qclip.transcribe import transcript_path
    from qclip.utils.ffmpeg import ffprobe

    config, brief = load_config(), load_campaign(slug)
    work = WORK_DIR / vid
    data = json.loads((work / "candidates.json").read_text(encoding="utf-8"))
    limit = top or config.clips.top_n
    chosen = [c for c in data["candidates"] if (c["id"] in ids if ids else c["id"] <= limit)]
    if ids and len(chosen) != len(ids):
        raise RuntimeError(f"candidats introuvables : {sorted(set(ids) - {c['id'] for c in chosen})}")
    if hook and len(chosen) != 1:
        raise RuntimeError("--hook ne s'utilise qu'avec un seul clip (--ids N)")
    out_dir = work / "renders" if brief.test_only else ROOT / "output" / slug / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    if brief.test_only:
        steps.info(f"campagne de test : rendus dans {out_dir.relative_to(ROOT)} avec le bandeau « {WATERMARK} »")

    windows = load_fetched(vid)
    probe = ffprobe(work / "windows" / windows[0]["file"])
    wanted = layout_name or brief.layout
    encoder = pick_encoder(config.render.encoder)
    mention = brief.required.mention

    results = []
    for c in chosen:
        out_path = out_dir / f"clip_{c['id']}.mp4"
        if out_path.exists() and not force:
            steps.info(f"clip_{c['id']}.mp4 existe déjà (--force pour refaire)")
            continue
        # La scène change pendant un live : la facecam se cherche dans chaque clip.
        facecam: Facecam | None = None
        if wanted == "facecam":
            if brief.facecam:
                facecam = Facecam("overlay", None, brief.facecam, "brief")
            else:
                facecam = detect_for_clip(work / c["file"], c["file_start"], c["duration"], probe.width,
                                          probe.height, work / "facecam" / f"cand_{c['id']}.json", force)  # fmt: skip
        layout, warning = choose_layout(wanted, facecam, config.render.fps, probe.width, probe.height)
        if warning:
            steps.info(f"clip {c['id']} : {warning}")
        words = json.loads(transcript_path(work / "windows", c["window"]).read_text(encoding="utf-8"))["words"]
        inside = [w for w in words if c["start"] <= w["start"] and w["end"] <= c["end"]]
        clip_hook = hook if hook is not None else c.get("hook") or default_hook(inside, c["start"])
        with steps.step(f"clip {c['id']} ({c['duration']:.0f} s, {layout.name}, {encoder})"):
            info = render_clip(c, work, out_path, layout, words, config.subtitle, config.render.lufs, encoder,
                               clip_hook, mention, brief.test_only)  # fmt: skip
        meta = {"candidate": c, "layout": layout.name, "facecam": asdict(facecam) if facecam else None,
                "encoder": encoder, "hook": clip_hook, **info}  # fmt: skip
        out_path.with_suffix(".render.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        steps.info(f"{out_path.relative_to(ROOT)} — accroche « {clip_hook} »")
        results.append({"path": out_path, **meta})
    return results
