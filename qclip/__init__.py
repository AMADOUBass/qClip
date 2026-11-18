"""qClip : clips verticaux sous-titrés en français à partir de VOD de campagnes de clipping."""

from pathlib import Path

__version__ = "0.1.0"

# Racine du projet (installé en mode éditable par `uv sync`) : config.yaml, campaigns/, input/, work/, output/, tools/.
ROOT = Path(__file__).resolve().parent.parent
