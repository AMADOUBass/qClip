# qClip

Outil CLI 100 % local pour les campagnes de clipping : il transforme les VOD d'autres créateurs
(streams Twitch/Kick, vidéos YouTube, fournies ou autorisées par une campagne) en clips verticaux
sous-titrés en français. Le design complet est dans `docs/SPEC.md` :
le lire avant chaque jalon, et le mettre à jour quand une décision change.

# Commandes
- Sync des dépendances : `uv sync`
- Lancer : `uv run qclip <commande>` (ex. `uv run qclip doctor`)
- Lint + format : `uvx ruff check --fix . && uvx ruff format .`
- Types : `uvx ty check` (ty est en beta : signaler un faux positif évident au lieu de le contourner)
- Tests : `uv run pytest -q` — un seul fichier : `uv run pytest tests/test_score.py -q`
- Vidéo de test : `input/sample.mp4` (5 min d'une VOD de campagne). Toujours valider dessus avant une longue VOD.
- Aucun téléchargement ni traitement de contenu qui n'est pas rattaché à une campagne (`campaigns/<slug>.yaml`).

# Git
- Dépôt : https://github.com/AMADOUBass/qClip (branche `main`). Un commit par jalon validé.
- **Jamais de ligne `Co-Authored-By: Claude …`** ni aucune mention de Claude / IA dans les messages de commit ou de PR.

# Machine
- Portable Windows, GPU intégré Intel UHD 620, **pas de carte Nvidia, pas de CUDA**. Tout le ML tourne sur le CPU.
- Modèles légers (ONNX int8), un seul modèle chargé à la fois, jamais de séparation ni de transcription sur une VOD entière
  (pipeline « repérer d'abord, traiter ensuite », voir SPEC §1).
- Encodage vidéo : `h264_qsv` (Intel Quick Sync), sinon `libx264 -preset veryfast`.
- torch en version CPU (index PyPI par défaut) ; ne pas configurer d'index CUDA.

# Conventions
- Python 3.12, type hints partout, `pathlib` pour tous les chemins.
- ffmpeg/ffprobe via `subprocess.run([...])` avec une liste d'arguments, jamais `shell=True`.
- Chaque étape écrit dans `work/<video_id>/` et réutilise son résultat s'il existe (`--force` pour refaire).
- Les modèles ML sont derrière une interface (ex. `Transcriber`) pour pouvoir changer de backend.
- Mesurer et afficher le temps de chaque étape (c'est le facteur limitant sur cette machine).
- Avant d'écrire du code pour yt-dlp, audio-separator, onnx-asr, faster-whisper, qwen-asr, transformers, ollama ou pysubs2 :
  vérifier l'API actuelle avec Context7 (ces libs changent vite).
- Un rendu n'est validé qu'après `/verify-clip` (images extraites et regardées), pas sur le seul code retour de ffmpeg.

# Pièges
- Ne jamais ouvrir les vidéos avec Read : utiliser ffprobe ou extraire des images dans `work/`.
- onnx-asr / Parakeet : 20–30 s d'audio max par appel → découper avec le VAD.
- Le build ffmpeg doit inclure QSV et libass ; `qclip doctor` le vérifie par un vrai test d'encodage.
