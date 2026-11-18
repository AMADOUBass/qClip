"""Interface en ligne de commande. Uniquement de l'affichage : la logique est dans les modules du cœur."""

import io
import sys
import time
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from qclip import ROOT
from qclip import doctor as doctor_mod
from qclip.campaign import load_brief, new_campaign
from qclip.config import ConfigError

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
