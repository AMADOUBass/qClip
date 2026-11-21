"""Interface en ligne de commande. Uniquement de l'affichage : la logique est dans les modules du cœur."""

import io
import json
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from yt_dlp.utils import DownloadError

from qclip import ROOT
from qclip import doctor as doctor_mod
from qclip.bench import SEP_MODELS, AsrResult, bench_asr, bench_sep, bench_vision
from qclip.campaign import load_brief, load_campaign, new_campaign
from qclip.candidates import build_candidates
from qclip.config import ConfigError, cpu_threads, load_config
from qclip.edits import corrected, load_edits
from qclip.fetch import fetch_windows
from qclip.ingest import ingest_windows
from qclip.pipeline import process_vod
from qclip.posts import campaign_stats, log_post
from qclip.render import clip_safety, render_candidates, write_meta
from qclip.rerank import key as rerank_key
from qclip.rerank import load_rerank, rerank_candidates
from qclip.scout import format_hms, load_scout, scout_source, scout_urls, scouted_videos
from qclip.sources import WORK_DIR
from qclip.steps import Steps
from qclip.transcribe import transcribe_windows, transcript_path

# Erreurs « attendues » : on affiche le message, sans trace Python.
USER_ERRORS = (ConfigError, RuntimeError, FileNotFoundError, DownloadError)

# Sortie redirigée sous Windows = cp1252 par défaut : accents et ✅ seraient illisibles. Fait à l'import,
# avant que Typer n'affiche quoi que ce soit (même --help).
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper) and _stream.encoding.lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer(
    help="qClip : clips verticaux sous-titrés en français à partir de VOD de campagnes.", no_args_is_help=True
)
campaign_app = typer.Typer(help="Gérer les briefs de campagne (campaigns/<slug>.yaml).", no_args_is_help=True)
app.add_typer(campaign_app, name="campaign")

console = Console()
ICONS = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}


@app.command()
def doctor() -> None:
    """Vérifie l'environnement : ffmpeg, Quick Sync, libass, RAM, disque, Ollama, config et briefs."""
    start = time.perf_counter()
    with console.status("Vérifications en cours (tests d'encodage réels)…"):
        checks = doctor_mod.run_checks()
    table = Table(title="qclip doctor", show_lines=False)
    table.add_column("", width=2)
    table.add_column("Vérification", style="bold")
    table.add_column("Détail")
    table.add_column("Temps", justify="right", style="dim")
    for check in checks:
        table.add_row(ICONS[check.status], check.name, check.detail, f"{check.seconds:.1f} s")
    console.print(table)

    # Une ligne par correctif : plusieurs ❌ ont souvent la même cause (ex. ffmpeg absent).
    fixes: dict[str, list[str]] = {}
    for c in checks:
        if c.status == "fail" and c.fix:
            fixes.setdefault(c.fix, []).append(c.name)
    if fixes:
        console.print("\n[bold red]Comment corriger :[/]")
        for fix, names in fixes.items():
            console.print(f"  ❌ [bold]{', '.join(names)}[/] → {fix}", soft_wrap=True)
    counts = {status: sum(c.status == status for c in checks) for status in ICONS}
    console.print(
        f"\n{counts['ok']} ✅  {counts['warn']} ⚠️   {counts['fail']} ❌  — total {time.perf_counter() - start:.1f} s"
    )
    if counts["fail"]:
        raise typer.Exit(code=1)


@campaign_app.command("new")
def campaign_new(slug: Annotated[str, typer.Argument(help="Identifiant court, ex. streamerx-gta6")]) -> None:
    """Crée campaigns/<slug>.yaml à partir du modèle campaigns/_template.yaml."""
    try:
        path = new_campaign(slug)
    except ConfigError as e:
        console.print(f"[red]❌ {e}[/]", soft_wrap=True)
        raise typer.Exit(code=1) from e
    console.print(f"✅ Campagne créée : {path.relative_to(ROOT)}")
    console.print("   Remplis-la avec le brief réel, puis vérifie avec [bold]qclip campaign check[/].")


@campaign_app.command("check")
def campaign_check(slug: Annotated[str, typer.Argument(help="Slug de la campagne à valider")]) -> None:
    """Valide campaigns/<slug>.yaml et affiche les champs fautifs."""
    try:
        brief = load_brief(ROOT / "campaigns" / f"{slug}.yaml")
    except ConfigError as e:
        console.print(f"[red]❌ {e}[/]", soft_wrap=True)
        raise typer.Exit(code=1) from e
    console.print(f"✅ {slug} : brief valide — « {brief.name} » ({', '.join(brief.platforms)}, layout {brief.layout})")
    if brief.test_only:
        console.print("   ⚠️  campagne de test : traitement local seulement, aucun clip prêt à poster")


def console_steps() -> Steps:
    return Steps(
        on_start=lambda name: console.print(f"[dim]⏳ {name}…[/]"),
        on_done=lambda name, seconds: console.print(f"✅ {name} [dim]— {seconds:.1f} s[/]"),
        on_info=lambda message: console.print(f"   {message}", soft_wrap=True),
    )


def fail(error: Exception) -> typer.Exit:
    console.print(f"[red]❌ {error}[/]", soft_wrap=True)
    return typer.Exit(code=1)


@app.command()
def scout(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    url: Annotated[str | None, typer.Option(help="Une seule source (elle doit être dans le brief)")] = None,
    force: Annotated[bool, typer.Option(help="Retélécharger chat et audio, tout recalculer")] = False,
) -> None:
    """Repérage léger sur la VOD entière : chat + audio basse qualité → meilleures fenêtres."""
    start = time.perf_counter()
    try:
        urls = scout_urls(campaign, url)
        if not urls:
            raise ConfigError(f"aucune source vidéo dans campaigns/{campaign}.yaml (champ sources)")
        for source in urls:
            console.rule(source)
            result = scout_source(campaign, source, console_steps(), force=force)
            table = Table(title=f"{len(result['windows'])} fenêtres — {result['video_id']}")
            for column in ["#", "Début", "Fin", "Pic", "Score", "Chat z", "Volume z"]:
                table.add_column(column, justify="right")
            for w in result["windows"]:
                table.add_row(
                    str(w["rank"]), format_hms(w["start"]), format_hms(w["end"]), format_hms(w["peak"]),
                    f"{w['score']:.2f}", f"{w['chat_z']:.1f}", f"{w['loudness_z']:.1f}",
                )  # fmt: skip
            console.print(table)
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


@app.command()
def fetch(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/), si plusieurs VOD repérées")] = None,
    max_height: Annotated[int, typer.Option(help="Hauteur vidéo maximale")] = 1080,
    force: Annotated[bool, typer.Option(help="Retélécharger les plages existantes")] = False,
    top: Annotated[int | None, typer.Option(help="Seulement les N meilleures fenêtres")] = None,
) -> None:
    """Télécharge seulement les plages vidéo des fenêtres trouvées par `qclip scout`."""
    start = time.perf_counter()
    try:
        videos = [video] if video else scouted_videos(campaign)
        if not videos:
            raise ConfigError(f"aucune VOD repérée pour {campaign!r} : lancer d'abord `qclip scout {campaign}`")
        for vid in videos:
            console.rule(vid)
            fetched = fetch_windows(
                campaign, load_scout(vid), console_steps(), max_height=max_height, force=force, top=top
            )
            console.print(f"✅ {len(fetched)} plages dans work/{vid}/windows/")
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


def campaign_videos(campaign: str, video: str | None) -> list[str]:
    """VOD repérées pour cette campagne. Un --video d'une autre campagne est refusé."""
    videos = scouted_videos(campaign)
    if video:
        if video not in videos:
            raise ConfigError(f"{video} n'appartient pas à la campagne {campaign!r} (repérées : {', '.join(videos)})")
        return [video]
    if not videos:
        raise ConfigError(f"aucune VOD repérée pour {campaign!r} : lancer d'abord `qclip scout {campaign}`")
    return videos


@app.command()
def ingest(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/)")] = None,
    top: Annotated[int | None, typer.Option(help="Seulement les N meilleures plages")] = None,
    separation: Annotated[bool, typer.Option(help="Séparer la voix (désactiver pour un podcast propre)")] = True,
    force: Annotated[bool, typer.Option(help="Refaire les plages déjà prêtes")] = False,
) -> None:
    """Audio de chaque plage → voix (mono 16 kHz) + reste (mono 48 kHz), séparation par audio-separator."""
    start = time.perf_counter()
    try:
        config = load_config()
        load_campaign(campaign)
        for vid in campaign_videos(campaign, video):
            console.rule(vid)
            ready = ingest_windows(
                vid, console_steps(), separation and config.separation.enabled, config.separation.model, top, force
            )
            console.print(f"✅ {len(ready)} plages prêtes dans work/{vid}/windows/")
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


@app.command()
def transcribe(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/)")] = None,
    top: Annotated[int | None, typer.Option(help="Seulement les N meilleures plages")] = None,
    backend: Annotated[str | None, typer.Option(help="parakeet | whisper | qwen3 (défaut : config.yaml)")] = None,
    force: Annotated[bool, typer.Option(help="Retranscrire les plages déjà faites")] = False,
) -> None:
    """Transcrit la voix de chaque plage → w_<n>.transcript.json (mots horodatés, temps de la VOD)."""
    start = time.perf_counter()
    try:
        config = load_config()
        brief = load_campaign(campaign)
        chosen = backend or config.asr.backend
        for vid in campaign_videos(campaign, video):
            console.rule(vid)
            done = transcribe_windows(
                vid,
                console_steps(),
                backend=chosen,
                model=config.asr.model if chosen == config.asr.backend else None,
                quantization=config.asr.quantization,
                language=brief.language,
                threads=cpu_threads(config),
                prompt=brief.creator,
                top=top,
                force=force,
            )
            console.print(f"✅ {len(done)} transcriptions dans work/{vid}/windows/")
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


def bench_table(title: str, results: list[AsrResult], first_label: str) -> Table:
    table = Table(title=title)
    for column in ["", "Modèle", "Chargement", "Calcul", "RTF", "Mots", "Confiance", f"Écart / {first_label}"]:
        table.add_column(column, justify="right" if column not in ("", "Modèle") else "left")
    for r in results:
        table.add_row(
            r.name,
            r.model,
            f"{r.load_s:.1f} s",
            f"{r.run_s:.1f} s",
            f"{r.rtf:.2f}" if r.run_s else "—",
            str(r.words),
            f"{r.confidence:.2f}" if r.confidence is not None else "—",
            f"{r.wer_vs_first:.0%}" if r.wer_vs_first is not None else "réf.",
        )
    return table


@app.command("bench-asr")
def bench_asr_cmd(
    audio: Annotated[Path, typer.Argument(help="Extrait d'une campagne (ex. work/<id>/windows/w_01.vocals.wav)")],
    backends: Annotated[str, typer.Option(help="Liste séparée par des virgules")] = "parakeet,whisper,qwen3",
) -> None:
    """Compare les backends de transcription : temps de chargement, de calcul, RTF, confiance, écart entre eux."""
    try:
        names = [b.strip() for b in backends.split(",") if b.strip()]
        results = bench_asr(audio, names, console_steps(), threads=cpu_threads(load_config()))
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(bench_table(f"bench-asr — {audio.name}", results, results[0].name))
    for r in results:
        console.print(f"\n[bold]{r.name}[/] : {r.text}", soft_wrap=True)


@app.command("bench-sep")
def bench_sep_cmd(
    audio: Annotated[Path, typer.Argument(help="Extrait d'une campagne (ex. work/<id>/windows/w_01.mp4)")],
    models: Annotated[str, typer.Option(help="Modèles audio-separator (virgules)")] = ",".join(SEP_MODELS),
) -> None:
    """Compare les modèles de séparation : temps, puis qualité de la transcription Parakeet de la voix obtenue."""
    try:
        names = [m.strip() for m in models.split(",") if m.strip()]
        results = bench_sep(audio, names, console_steps(), threads=cpu_threads(load_config()))
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(bench_table(f"bench-sep — {audio.name}", results, "audio brut"))
    for r in results:
        console.print(f"\n[bold]{r.name}[/] : {r.text}", soft_wrap=True)


@app.command("bench-vision")
def bench_vision_cmd(
    clip: Annotated[Path, typer.Argument(help="Clip rendu (ex. output/<campagne>/<vid>/clip_1.mp4)")],
    models: Annotated[
        str, typer.Option(help="Modèles Ollama vision séparés par des virgules")
    ] = "qwen3.5:2b-q4_K_M,qwen3.5:4b-q4_K_M",
    thumbnail: Annotated[Path | None, typer.Option(help="Miniature JPEG (optionnel)")] = None,
) -> None:
    """Compare des modèles vision Ollama sur les 7 premières secondes d'un clip : temps et verdict de démonétisation."""
    try:
        names = [m.strip() for m in models.split(",") if m.strip()]
        results = bench_vision(clip, names, thumbnail)
    except USER_ERRORS as e:
        raise fail(e) from e
    table = Table(title=f"bench-vision — {clip.name}")
    for col, just in [
        ("Modèle", "left"),
        ("Violent", "left"),
        ("Gore", "left"),
        ("Signalé", "left"),
        ("Confiance", "right"),
        ("Temps", "right"),
        ("Description", "left"),
    ]:
        table.add_column(col, justify=just)
    for r in results:
        table.add_row(
            r.model,
            "⚠️ " if r.graphic_violence else "✅",
            "⚠️ " if r.gore else "✅",
            "[red]OUI[/]" if r.flagged else "[green]non[/]",
            f"{r.confidence:.2f}",
            f"{r.seconds:.1f} s",
            r.description,
        )
    console.print(table)


@app.command()
def candidates(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/)")] = None,
    clap: Annotated[bool | None, typer.Option(help="Événements audio CLAP (défaut : config.yaml)")] = None,
    scenes: Annotated[bool | None, typer.Option(help="Coupes de scène (défaut : config.yaml)")] = None,
    force: Annotated[bool, typer.Option(help="Recalculer les signaux en cache")] = False,
) -> None:
    """Signaux fins sur chaque plage + meilleur passage de chacune → candidates.json, classés par score."""
    start = time.perf_counter()
    try:
        load_campaign(campaign)
        for vid in campaign_videos(campaign, video):
            console.rule(vid)
            found = build_candidates(campaign, vid, console_steps(), use_clap=clap, use_scenes=scenes, force=force)
            table = Table(title=f"{len(found)} candidats — {vid}", show_lines=True)
            for column in ["#", "Début", "Durée", "Score"]:
                table.add_column(column, justify="right")
            for column in ["Plage", "Raisons", "Extrait"]:
                table.add_column(column)
            for c in found:
                table.add_row(
                    str(c["id"]), format_hms(c["start"]), f"{c['duration']:.0f} s", f"{c['score']:.2f}",
                    f"w_{c['window']:02d} @ {c['file_start']:.0f} s", ", ".join(c["reasons"]) or "—",
                    c["text"][:140] + ("…" if len(c["text"]) > 140 else ""),
                )  # fmt: skip
            console.print(table)
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


@app.command()
def render(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/)")] = None,
    ids: Annotated[str | None, typer.Option(help="Candidats à rendre, ex. 1,3,5 (défaut : les top_n premiers)")] = None,
    top: Annotated[int | None, typer.Option(help="Rendre les N meilleurs candidats")] = None,
    layout: Annotated[str | None, typer.Option(help="facecam | blur (défaut : le brief)")] = None,
    hook: Annotated[str | None, typer.Option(help="Accroche imposée (avec un seul --ids)")] = None,
    force: Annotated[bool, typer.Option(help="Refaire les clips déjà rendus")] = False,
    kept: Annotated[bool, typer.Option(help="Rendre les moments gardés au tri (interface)")] = False,
) -> None:
    """Rend les candidats en clips verticaux 1080x1920 : layout, sous-titres mot par mot, accroche, loudnorm."""
    start = time.perf_counter()
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()] if ids else None
        for vid in campaign_videos(campaign, video):
            console.rule(vid)
            done = render_candidates(campaign, vid, wanted, top, console_steps(), layout, hook, force, kept)
            console.print(f"✅ {len(done)} clip(s) rendu(s)")
    except (*USER_ERRORS, ValueError) as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


@app.command()
def rerank(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/)")] = None,
    top: Annotated[int | None, typer.Option(help="Nombre de candidats à noter (défaut : 2 × top_n)")] = None,
    force: Annotated[bool, typer.Option(help="Renoter les candidats déjà notés")] = False,
) -> None:
    """(Optionnel) Un LLM local (Ollama) note les meilleurs candidats et propose accroche + titre."""
    start = time.perf_counter()
    try:
        for vid in campaign_videos(campaign, video):
            console.rule(vid)
            path = rerank_candidates(campaign, vid, console_steps(), top, force)
            console.print(f"✅ notes dans {path.relative_to(ROOT)} — `qclip render` les utilise")
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


@app.command()
def meta(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/)")] = None,
    ids: Annotated[str | None, typer.Option(help="Clips, ex. 1,3 (défaut : tous les clips rendus)")] = None,
) -> None:
    """Refait titre, légende, miniature et conformité des clips déjà rendus (sans réencoder la vidéo)."""
    try:
        wanted = {int(x) for x in ids.split(",") if x.strip()} if ids else None
        brief = load_campaign(campaign)
        for vid in campaign_videos(campaign, video):
            out_dir = WORK_DIR / vid / "renders" if brief.test_only else ROOT / "output" / campaign / vid
            for render_json in sorted(out_dir.glob("clip_*.render.json")):
                info = json.loads(render_json.read_text(encoding="utf-8"))
                c = info["candidate"]
                if wanted and c["id"] not in wanted:
                    continue
                words = json.loads(transcript_path(WORK_DIR / vid / "windows", c["window"]).read_text("utf-8"))
                inside = [w for w in words["words"] if c["start"] <= w["start"] and w["end"] <= c["end"]]
                llm = load_rerank(vid).get(rerank_key(c), {})
                post = write_meta(campaign, vid, c, out_dir / f"clip_{c['id']}.mp4", inside, llm)
                flag = "✅" if post["compliance"]["ok"] else "⚠️ "
                console.print(f"{flag} clip {c['id']} — « {post['title']} »", soft_wrap=True)
    except (*USER_ERRORS, ValueError) as e:
        raise fail(e) from e


@app.command()
def safety(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    video: Annotated[str | None, typer.Option(help="video_id (work/<video_id>/)")] = None,
    ids: Annotated[str | None, typer.Option(help="Clips, ex. 1,3 (défaut : tous les clips rendus)")] = None,
) -> None:
    """Risque de démonétisation des clips rendus : gros mots ou sons violents dans les 7 premières secondes."""
    try:
        wanted = {int(x) for x in ids.split(",") if x.strip()} if ids else None
        config, brief = load_config(), load_campaign(campaign)
        for vid in campaign_videos(campaign, video):
            out_dir = WORK_DIR / vid / "renders" if brief.test_only else ROOT / "output" / campaign / vid
            edits = load_edits(vid)
            for render_json in sorted(out_dir.glob("clip_*.render.json")):
                c = json.loads(render_json.read_text(encoding="utf-8"))["candidate"]
                if wanted and c["id"] not in wanted:
                    continue
                raw = json.loads(transcript_path(WORK_DIR / vid / "windows", c["window"]).read_text("utf-8"))["words"]
                words = corrected(raw, edits.get(c["window"], {}).get("corrections", {}))
                verdict = clip_safety(vid, c, words, config.audio_event_labels, brief.clip.min_len)
                clip = out_dir / f"clip_{c['id']}.mp4"
                clip.with_suffix(".safety.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
                post_path = clip.with_suffix(".json")
                if post_path.exists():  # le pipeline lit le verdict dans clip_<n>.json
                    post = json.loads(post_path.read_text(encoding="utf-8"))
                    post_path.write_text(json.dumps({**post, "safety": verdict}, ensure_ascii=False, indent=2), "utf-8")
                if verdict["ok"]:
                    console.print(f"✅ clip {c['id']} — rien dans les 7 premières secondes")
                    continue
                found = ", ".join(f"{f['kind']} « {f['detail']} » à {f['at']:.1f} s" for f in verdict["flags"])
                fix = f"décaler le début de {verdict['shift_s']} s" if verdict["shift_s"] else "aucun décalage possible"
                console.print(f"⚠️  clip {c['id']} — {found} → {fix}", soft_wrap=True)
    except (*USER_ERRORS, ValueError) as e:
        raise fail(e) from e


@app.command()
def log(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    clip: Annotated[str, typer.Argument(help="Numéro du clip (ex. 3) ou <video_id>/3")],
    platform: Annotated[str, typer.Option(help="tiktok | shorts | reels")],
    url: Annotated[str | None, typer.Option(help="URL du post")] = None,
    views: Annotated[int | None, typer.Option(help="Nombre de vues (à mettre à jour quand tu veux)")] = None,
    paid: Annotated[float | None, typer.Option(help="Montant payé pour ce post ($)")] = None,
) -> None:
    """Enregistre un post (URL), ses vues et/ou ce qui a été payé dans input/<campagne>/posts.csv."""
    try:
        row = log_post(campaign, clip, platform, url, views, paid)
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"✅ clip {row['clip_id']} sur {row['platform']} : {row['post_url']} — {row['views'] or 0} vues")


@app.command()
def stats(campaign: Annotated[str, typer.Argument(help="Slug de la campagne")]) -> None:
    """Clips rendus, postés, vues saisies et gains estimés (vues / 1000 × rate_per_1k du brief)."""
    try:
        s = campaign_stats(campaign)
    except USER_ERRORS as e:
        raise fail(e) from e
    table = Table(title=f"Stats — {campaign}")
    for column in ["Plateforme", "Posts", "Vues"]:
        table.add_column(column, justify="right" if column != "Plateforme" else "left")
    for platform, (n, v) in sorted(s.by_platform.items()):
        table.add_row(platform, str(n), f"{v:,}".replace(",", " "))
    console.print(table)
    views = f"{s.views:,}".replace(",", " ")
    console.print(f"{s.rendered} clip(s) rendu(s), {s.posted} post(s), {views} vues → ≈ {s.earnings:.2f} $ estimés")
    budget = f" · budget restant {s.budget_left:.2f} $ / {s.budget_total:.2f} $" if s.budget_total is not None else ""
    console.print(f"Payé : {s.paid:.2f} ${budget}")


@app.command()
def process(
    campaign: Annotated[str, typer.Argument(help="Slug de la campagne")],
    url: Annotated[str | None, typer.Option(help="Une seule source (elle doit être dans le brief)")] = None,
    force: Annotated[bool, typer.Option(help="Tout refaire (téléchargements compris)")] = False,
) -> None:
    """Chaîne complète d'une VOD : repérage → plages → audio → transcription → candidats."""
    start = time.perf_counter()
    try:
        for source in scout_urls(campaign, url):
            console.rule(source)
            vid = process_vod(campaign, source, console_steps(), force)
            console.print(f"✅ {vid} prête : `qclip candidates {campaign} --video {vid}` puis `qclip render`")
    except USER_ERRORS as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Port local de l'API")] = 8765,
) -> None:
    """Lance l'API locale de l'interface (http://127.0.0.1:8765, jamais exposée sur le réseau)."""
    from qclip.server import serve as run_server

    console.print(f"API qClip sur http://127.0.0.1:{port}  (docs : /docs) — Ctrl+C pour arrêter")
    run_server(port=port)
