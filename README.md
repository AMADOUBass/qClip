# qClip

Outil CLI 100 % local : VOD d'une campagne de clipping → clips verticaux sous-titrés en français.
Spécification : [docs/SPEC.md](docs/SPEC.md). Consignes de travail : [CLAUDE.md](CLAUDE.md).

```powershell
uv sync                          # installe Python 3.12 et les dépendances
uv run qclip doctor              # vérifie l'environnement
uv run qclip campaign new <slug> # crée campaigns/<slug>.yaml depuis le modèle
uv run qclip campaign check <slug>
uv run pytest -q
```

Prérequis hors Python : ffmpeg avec QSV et libass (`winget install Gyan.FFmpeg.Essentials`).
