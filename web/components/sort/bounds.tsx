"use client";

// Forme d'onde de la plage (maquette 4) : passage retenu en jaune, poignées pour ajuster le début et la fin
// (bornées par la durée min / max du brief), clic pour se placer, tête de lecture bleue.
// Tous les temps sont dans le fichier de la plage (secondes depuis son début).

import { useRef } from "react";

import { stamp } from "@/lib/format";
import { cn } from "@/lib/utils";

const BARS = 120;

type Props = {
  peaks: number[];
  duration: number;
  start: number;
  end: number;
  playhead: number;
  minLen: number;
  maxLen: number;
  offset: number; // début de la plage dans la VOD, pour afficher « Début 02:14:01 »
  onChange: (start: number, end: number) => void;
  onCommit: (start: number, end: number) => void;
  onSeek: (t: number) => void;
};

export function Bounds({ peaks, duration, start, end, playhead, minLen, maxLen, offset, onChange, onCommit, onSeek }: Props) {
  const area = useRef<HTMLDivElement>(null);
  const bars = Array.from({ length: BARS }, (_, i) => {
    if (!peaks.length) return 0.3;
    const a = Math.floor((i / BARS) * peaks.length);
    const b = Math.max(a + 1, Math.floor(((i + 1) / BARS) * peaks.length));
    return Math.max(...peaks.slice(a, b));
  });
  const pct = (t: number) => `${(t / duration) * 100}%`;
  const timeAt = (clientX: number) => {
    const box = area.current?.getBoundingClientRect();
    return box ? Math.min(Math.max(((clientX - box.left) / box.width) * duration, 0), duration) : 0;
  };
  const clamp = (edge: "start" | "end", t: number): [number, number] =>
    edge === "start"
      ? [Math.min(Math.max(t, end - maxLen, 0), end - minLen), end]
      : [start, Math.max(Math.min(t, start + maxLen, duration), start + minLen)];

  const handle = (edge: "start" | "end") => ({
    onPointerDown: (e: React.PointerEvent) => {
      e.stopPropagation();
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    onPointerMove: (e: React.PointerEvent) => {
      if (e.buttons & 1) onChange(...clamp(edge, timeAt(e.clientX)));
    },
    onPointerUp: (e: React.PointerEvent) => onCommit(...clamp(edge, timeAt(e.clientX))),
  });

  return (
    <div className="card-qc px-6 pt-5 pb-4">
      <div ref={area} className="relative h-24 cursor-pointer select-none" onPointerDown={(e) => onSeek(timeAt(e.clientX))}>
        <div className="absolute inset-0 flex items-center gap-[3px]">
          {bars.map((v, i) => {
            const t = ((i + 0.5) / BARS) * duration;
            return (
              <span key={i} className={cn("flex-1 rounded-full", t >= start && t <= end ? "bg-yellow" : "bg-[#cfd1d9]")}
                    style={{ height: `${Math.round(18 + v * 72)}%` }} />
            );
          })}
        </div>
        <div className="pointer-events-none absolute inset-y-0 rounded-xl border-[3px] border-yellow" style={{ left: pct(start), width: pct(end - start) }} />
        <span className="pointer-events-none absolute inset-y-0 w-0.5 bg-blue" style={{ left: pct(playhead) }} />
        {(["start", "end"] as const).map((edge) => (
          <span key={edge} role="slider" tabIndex={-1} aria-label={edge === "start" ? "Début du clip" : "Fin du clip"}
                aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(edge === "start" ? start : end)}
                {...handle(edge)}
                className="absolute top-1/2 h-14 w-4 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full border-2 border-surface bg-yellow shadow"
                style={{ left: pct(edge === "start" ? start : end) }} />
        ))}
      </div>
      <div className="mt-3 flex justify-between font-mono text-sm text-muted-foreground">
        <span>Début {stamp(offset + start)}</span>
        <span>Glisse les poignées pour ajuster</span>
        <span>Fin {stamp(offset + end)}</span>
      </div>
    </div>
  );
}
