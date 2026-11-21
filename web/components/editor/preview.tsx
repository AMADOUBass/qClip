"use client";

// Aperçu 9:16 en direct (maquette 5), sans rendu : la vidéo de la plage est dessinée sur un canvas avec les mêmes
// découpes que les filtres ffmpeg de qclip/render.py (blur_layout, facecam_layout), puis le texte est posé
// aux positions du rendu (sous-titres, accroche, mention, bandeau de test, overlay du brief).
// Coordonnées du rendu : 1080 x 1920 ; tout est mis à l'échelle de l'aperçu.

import { useEffect, useRef } from "react";

import { activeAt, timedLines } from "@/components/editor/subtitles";
import { API, type EditorData, type SubtitleStyle, media } from "@/lib/api";
import { cn } from "@/lib/utils";

export const RW = 1080;
export const RH = 1920;
const CW = 540; // canvas : moitié de la résolution du rendu (suffisant pour l'aperçu, léger pour le GPU intégré)
const CH = 960;
const FONT_SCALE = 0.65; // taille ASS (libass) → taille CSS de Montserrat, mesurée sur un vrai rendu (même largeur de texte)
const FONT = "QclipSubs";

type Props = {
  data: EditorData;
  video: HTMLVideoElement | null;
  clipTime: number;
  style: SubtitleStyle;
  hook: string;
  safeZones: boolean;
  zoom: number; // variation anti-doublon : agrandit l'image seulement (le texte est posé après, comme au rendu)
};

/** Dessine l'image courante de la vidéo selon le layout réellement rendu. */
function draw(ctx: CanvasRenderingContext2D, small: HTMLCanvasElement, v: HTMLVideoElement, data: EditorData) {
  const [sw, sh] = [v.videoWidth || data.source_size[0], v.videoHeight || data.source_size[1]];
  const k = CW / RW;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, CW, CH);
  const rect = data.facecam?.rect;
  if (data.preview.layout === "crop" && data.preview.crop) {
    // crop=<largeur>:<hauteur>:<x>:0 puis agrandi en 1080 x 1920
    const [x, width] = data.preview.crop;
    ctx.drawImage(v, x, 0, width, sh, 0, 0, CW, CH);
    return;
  }
  if (data.preview.layout === "facecam" && rect) {
    const [x, y, w, h] = rect;
    const topH = data.preview.top_h * k;
    // [a]crop=rect, scale … increase, crop centré → webcam en haut
    const s = Math.max(CW / w, topH / h);
    const cw = CW / s, ch = topH / s;
    ctx.drawImage(v, x + (w - cw) / 2, y + (h - ch) / 2, cw, ch, 0, 0, CW, topH);
    // [b] bande centrale du jeu au format de la zone du bas
    const gw = Math.min(sw, Math.round((sh * RW) / (RH - data.preview.top_h)));
    ctx.drawImage(v, (sw - gw) / 2, 0, gw, sh, 0, topH, CW, CH - topH);
    return;
  }
  // blur : fond = recadrage centré 9:16, très flou (calculé en petit puis agrandi, comme le rendu), assombri
  const cropW = (sh * 9) / 16;
  const sctx = small.getContext("2d");
  if (sctx) {
    sctx.drawImage(v, (sw - cropW) / 2, 0, cropW, sh, 0, 0, small.width, small.height);
    ctx.imageSmoothingQuality = "high";
    ctx.filter = "blur(6px)";
    ctx.drawImage(small, -12, -12, CW + 24, CH + 24);
    ctx.filter = "none";
  }
  ctx.fillStyle = "rgba(0,0,0,0.08)";
  ctx.fillRect(0, 0, CW, CH);
  const fgH = data.preview.fg_h * k;
  ctx.drawImage(v, 0, 0, sw, sh, 0, (CH - fgH) / 2, CW, fgH);
}

export function Preview({ data, video, clipTime, style, hook, safeZones, zoom }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);

  // Image : redessinée à chaque image décodée (requestVideoFrameCallback) et après chaque saut.
  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!video || !ctx) return;
    const small = Object.assign(document.createElement("canvas"), { width: 27, height: 48 });
    let handle = 0;
    let stopped = false;
    const paint = () => video.readyState >= 2 && draw(ctx, small, video, data);
    const loop = () => {
      paint();
      if (!stopped) handle = video.requestVideoFrameCallback(loop);
    };
    handle = video.requestVideoFrameCallback(loop);
    video.addEventListener("seeked", paint);
    video.addEventListener("loadeddata", paint);
    paint();
    return () => {
      stopped = true;
      video.cancelVideoFrameCallback(handle);
      video.removeEventListener("seeked", paint);
      video.removeEventListener("loadeddata", paint);
    };
  }, [video, data]);

  const sub = data.subtitle;
  const lines = timedLines(data.words, sub.words_per_line, data.preview.line_gap, data.preview.hold, data.duration);
  const active = activeAt(lines, clipTime);
  const up = (t: string) => (sub.uppercase ? t.toUpperCase() : t);
  const pctY = (y: number) => `${(y / RH) * 100}%`;
  const pctX = (x: number) => `${(x / RW) * 100}%`;
  const [ml, mr] = data.preview.margins;

  return (
    <div className="relative aspect-[9/16] w-full overflow-hidden rounded-[2rem] bg-ink [container-type:inline-size]"
         style={{ ["--k" as string]: `calc(100cqw / ${RW})` }}>
      <style>{`@font-face{font-family:${FONT};src:url(${API}/media/assets/fonts/Montserrat-ExtraBold.ttf);font-weight:800}`}</style>
      <canvas ref={canvas} width={CW} height={CH} className="absolute inset-0 size-full" style={{ transform: `scale(${zoom})` }} />

      {data.overlay?.url && (
        // eslint-disable-next-line @next/next/no-img-element -- overlay du brief, servi par l'API locale
        <img src={media(data.overlay.url)} alt="Overlay du brief" className="absolute"
             style={{ left: pctX(data.overlay.x * RW), top: pctY(data.overlay.y * RH), width: `${data.overlay.width * 100}%` }} />
      )}

      {/* Sous-titres : \pos(540, subs_y), centrés, largeur utile 1080 - marges */}
      {active && (
        <p className="absolute -translate-x-1/2 -translate-y-1/2 text-center leading-[1.15]"
           style={{ left: "50%", top: pctY(data.preview.subs_y), width: pctX(RW - ml - mr), fontFamily: FONT, fontWeight: 800,
                    fontSize: `calc(var(--k) * ${sub.size * FONT_SCALE})`, color: sub.color }}>
          {active.line.words.map((w, i) => (
            <span key={`${w.start}-${i}`}>
              {i > 0 && " "}
              <Word text={up(w.text)} style={style} state={style === "karaoke" ? (clipTime >= w.start ? "on" : "off") : i === active.word ? "on" : "off"}
                    highlight={sub.highlight} outline={sub.outline} />
            </span>
          ))}
        </p>
      )}

      {/* Accroche : 3 s, boîte blanche, \pos(540, hook_y) */}
      {hook && clipTime < data.preview.hook_seconds && (
        <p className="absolute -translate-x-1/2 -translate-y-1/2 text-center leading-[1.2] text-black"
           style={{ left: "50%", top: pctY(data.preview.hook_y), width: "max-content", maxWidth: pctX(RW - ml - mr), fontFamily: FONT, fontWeight: 800,
                    fontSize: `calc(var(--k) * ${Math.round(sub.size * 0.8) * FONT_SCALE})`,
                    background: "#fff", padding: "calc(var(--k) * 14)", boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" }}>
          {hook.toUpperCase()}
        </p>
      )}

      {data.mention && <Small text={data.mention} x={ml} y={data.preview.safe_bottom - 50} color="#fff" />}
      {data.preview.watermark && <Small text={data.preview.watermark} x={ml} y={150} color="#ff3030" />}

      {safeZones && (
        <>
          <div className="absolute inset-x-0 bottom-0 grid place-items-center bg-[repeating-linear-gradient(135deg,rgba(214,31,79,.35)_0_10px,rgba(214,31,79,.15)_10px_20px)] font-mono text-xs tracking-wider text-white"
               style={{ top: pctY(data.preview.safe_bottom) }}>PSEUDO · LÉGENDE · MUSIQUE</div>
          <div className="absolute top-[35%] right-0 grid place-items-center bg-[repeating-linear-gradient(135deg,rgba(214,31,79,.35)_0_10px,rgba(214,31,79,.15)_10px_20px)]"
               style={{ width: pctX(mr), bottom: `${100 - (data.preview.safe_bottom / RH) * 100}%` }}>
            <span className="rotate-90 font-mono text-xs tracking-wider whitespace-nowrap text-white">BOUTONS</span>
          </div>
        </>
      )}
    </div>
  );
}

/** Mot selon le style (active_word dans subtitles.py) : néon = couleur, boîte = bloc de couleur, contour = contour coloré. */
function Word({ text, style, state, highlight, outline }: { text: string; style: SubtitleStyle; state: "on" | "off"; highlight: string; outline: number }) {
  const stroke = (width: number, color: string) => ({
    WebkitTextStroke: `calc(var(--k) * ${width * 2}) ${color}`,
    paintOrder: "stroke fill",
  });
  const base = { ...stroke(outline, "#000"), textShadow: "calc(var(--k) * 2) calc(var(--k) * 2) 0 rgba(0,0,0,.5)" };
  if (state === "off") return <span style={base}>{text}</span>;
  if (style === "box")
    return <span className={cn("rounded-[calc(var(--k)*8)]")} style={{ background: highlight, color: "#000", padding: "0 calc(var(--k) * 14)", boxShadow: `0 0 0 calc(var(--k) * 4) ${highlight}` }}>{text}</span>;
  if (style === "outline") return <span className="inline-block scale-[1.08]" style={{ ...stroke(10, highlight) }}>{text}</span>;
  return <span style={{ ...base, color: highlight }}>{text}</span>; // néon et karaoké (déjà prononcé)
}

function Small({ text, x, y, color }: { text: string; x: number; y: number; color: string }) {
  return (
    <span className="absolute -translate-y-1/2 whitespace-nowrap"
          style={{ left: `${(x / RW) * 100}%`, top: `${(y / RH) * 100}%`, color, fontFamily: FONT, fontWeight: 800,
                   fontSize: `calc(var(--k) * ${40 * FONT_SCALE})`, WebkitTextStroke: "calc(var(--k) * 6) #000", paintOrder: "stroke fill" }}>
      {text}
    </span>
  );
}
