"""Interface en ligne de commande. Uniquement de l'affichage : la logique est dans les modules du cœur."""

import io
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
from qclip.bench import SEP_MODELS, AsrResult, bench_asr, bench_sep
from qclip.campaign import load_brief, load_campaign, new_campaign
from qclip.candidates import build_candidates
from qclip.config import ConfigError, cpu_threads, load_config
from qclip.fetch import fetch_windows
from qclip.ingest import ingest_windows
from qclip.render import render_candidates
from qclip.scout import format_hms, load_scout, scout_source, scout_urls, scouted_videos
from qclip.steps import Steps
from qclip.transcribe import transcribe_windows

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
) -> None:
    """Rend les candidats en clips verticaux 1080x1920 : layout, sous-titres mot par mot, accroche, loudnorm."""
    start = time.perf_counter()
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()] if ids else None
        for vid in campaign_videos(campaign, video):
            console.rule(vid)
            done = render_candidates(campaign, vid, wanted, top, console_steps(), layout, hook, force)
            console.print(f"✅ {len(done)} clip(s) rendu(s)")
    except (*USER_ERRORS, ValueError) as e:
        raise fail(e) from e
    console.print(f"Total : {time.perf_counter() - start:.1f} s")
