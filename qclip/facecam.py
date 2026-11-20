"""Zone facecam du streamer (SPEC §4.8), détectée **par clip** avec YuNet, ou fixée dans le brief.

Un streamer change de scène pendant un live (caméra plein cadre, partage d'écran, match avec webcam incrustée) :
la détection se fait donc sur quelques images de chaque clip, pas une fois pour toute la VOD.

Pièges vus sur une vraie VOD : YuNet trouve aussi les visages du contenu (arbitre, vidéo TikTok) et du décor
(poster, tableau, avatars). D'où les règles :
1. un grand visage (≥ 10 % de la largeur) → caméra plein cadre ;
2. sinon, la webcam est un visage de taille webcam, présent sur plusieurs images au même endroit, dans un coin,
   et de préférence qui **bouge un peu** (un poster, un avatar ou une image figée ne bougent pas du tout) ;
3. sinon, un grand visage vu sur une seule image (le streamer s'est levé) → caméra plein cadre.
"""

import json
import statistics
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from qclip import ROOT

YUNET = ROOT / "models" / "yunet" / "face_detection_yunet_2026may.onnx"
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2026may.onnx"
)
FULLCAM_MIN_WIDTH = 0.10  # visage ≥ 10 % de la largeur de l'image → caméra plein cadre
WEBCAM_FACE_PX = (24, 200)  # largeur d'un visage dans une webcam incrustée (source 1080p)
CORNER_X, CORNER_Y = 0.25, 0.30  # « dans un coin » : 25 % extérieurs en largeur ET 30 % extérieurs en hauteur
TRACK_RADIUS = 80  # deux détections à moins de 80 px = le même visage
MOVING_PX = 2.0  # écart-type de position au-delà duquel un visage « bouge » (vivant)
WEBCAM_SCALE = 7.0  # zone ≈ 7 × la largeur du visage : reste dans la webcam (8 × débordait sur le jeu)
FACECAM_ASPECT = 1080 / 640  # zone du haut du layout facecam (1080 x 640)


@dataclass
class Facecam:
    mode: str  # "overlay" (webcam incrustée), "fullcam" (caméra plein cadre), "none" (aucun visage)
    face: list[int] | None  # x, y, w, h du visage retenu (pixels de la source)
    rect: list[int] | None  # x, y, w, h de la zone à mettre en haut (overlay seulement)
    source: str  # "yunet" ou "brief"


def frame_at(video: Path, t: float, width: int, height: int) -> np.ndarray | None:
    """Une image BGR (width x height) à l'instant t, via ffmpeg (pas de dépendance au décodeur d'OpenCV)."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
           "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]  # fmt: skip
    out = subprocess.run(cmd, capture_output=True, check=False, timeout=60).stdout
    if len(out) != width * height * 3:
        return None
    return np.frombuffer(out, dtype=np.uint8).reshape(height, width, 3)


def detect_faces(frames: list[np.ndarray]) -> list[list[list[float]]]:
    """Tous les visages de chaque image (x, y, w, h), en pleine résolution : un visage de webcam fait ~50 px."""
    import cv2

    if not YUNET.exists():
        raise FileNotFoundError(f"modèle YuNet absent : le télécharger dans {YUNET} depuis {YUNET_URL}")
    if not frames:
        return []
    h, w = frames[0].shape[:2]
    detector = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), 0.6, 0.3, 50)
    out = []
    for frame in frames:
        _, faces = detector.detect(frame)
        out.append([[float(v) for v in f[:4]] for f in faces] if faces is not None else [])
    return out


def tracks(per_frame: list[list[list[float]]]) -> list[list[list[float]]]:
    """Regroupe les détections des différentes images par position (un groupe = un même visage)."""
    groups: list[list[list[float]]] = []
    for faces in per_frame:
        for f in faces:
            cx, cy = f[0] + f[2] / 2, f[1] + f[3] / 2
            for g in groups:
                gx = statistics.median(x[0] + x[2] / 2 for x in g)
                gy = statistics.median(x[1] + x[3] / 2 for x in g)
                if abs(cx - gx) <= TRACK_RADIUS and abs(cy - gy) <= TRACK_RADIUS:
                    g.append(f)
                    break
            else:
                groups.append([f])
    return groups


def rect_around_face(face: list[float], src_w: int, src_h: int) -> list[int]:
    """Zone webcam estimée autour du visage (≈ 7 × sa largeur), au format de la zone du haut, dans l'image."""
    x, y, w, h = face
    rw = min(src_w * 0.4, w * WEBCAM_SCALE)
    rh = min(src_h, rw / FACECAM_ASPECT)
    rw = rh * FACECAM_ASPECT
    cx, cy = x + w / 2, y + h * 0.6  # un peu sous le centre du visage : on garde les épaules
    rx = min(max(0.0, cx - rw / 2), src_w - rw)
    ry = min(max(0.0, cy - rh / 2), src_h - rh)
    return [round(rx), round(ry), round(rw), round(rh)]


def classify(per_frame: list[list[list[float]]], src_w: int, src_h: int, min_hits: int = 2) -> Facecam:
    """Détections de plusieurs images → caméra plein cadre, webcam incrustée ou rien."""
    stable = [g for g in tracks(per_frame) if len(g) >= min_hits]
    if not stable:
        return Facecam("none", None, None, "yunet")

    def median_box(g: list[list[float]]) -> list[float]:
        return [statistics.median(f[i] for f in g) for i in range(4)]

    big = [g for g in stable if median_box(g)[2] >= FULLCAM_MIN_WIDTH * src_w]
    if big:
        face = median_box(max(big, key=lambda g: median_box(g)[2]))
        return Facecam("fullcam", [round(v) for v in face], None, "yunet")

    best, best_score = None, -1.0
    for g in stable:
        x, y, w, h = median_box(g)
        cx, cy = (x + w / 2) / src_w, (y + h / 2) / src_h
        in_corner = (cx < CORNER_X or cx > 1 - CORNER_X) and (cy < CORNER_Y or cy > 1 - CORNER_Y)
        if not (WEBCAM_FACE_PX[0] <= w <= WEBCAM_FACE_PX[1]) or not in_corner:
            continue
        motion = float(np.std([f[0] + f[2] / 2 for f in g]) + np.std([f[1] + f[3] / 2 for f in g]))
        score = abs(cx - 0.5) * 2 + abs(cy - 0.5) * 2 + (1.0 if motion >= MOVING_PX else 0.0)
        if score > best_score:
            best, best_score = [x, y, w, h], score
    if best is not None:
        return Facecam("overlay", [round(v) for v in best], rect_around_face(best, src_w, src_h), "yunet")
    seen_big = [f for faces in per_frame for f in faces if f[2] >= FULLCAM_MIN_WIDTH * src_w]
    if seen_big:
        return Facecam("fullcam", [round(v) for v in max(seen_big, key=lambda f: f[2])], None, "yunet")
    return Facecam("none", None, None, "yunet")


def detect_for_clip(
    video: Path, start: float, duration: float, src_w: int, src_h: int, cache: Path, force: bool = False
) -> Facecam:
    """3 images du clip (début, milieu, fin) → Facecam ; résultat en cache (un fichier par clip)."""
    if cache.exists() and not force:
        return Facecam(**json.loads(cache.read_text(encoding="utf-8")))
    times = [start + min(2.0, duration / 4), start + duration / 2, start + max(duration - 2.0, duration * 3 / 4)]
    frames = [f for f in (frame_at(video, t, src_w, src_h) for t in times) if f is not None]
    result = classify(detect_faces(frames), src_w, src_h)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    return result
