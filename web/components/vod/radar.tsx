"use client";

// « Radar du hype » (maquette 3) : chat vers le haut (bleu), volume vers le bas (gris), zones repérées en jaune
// avec leur numéro (rang : #01 = la zone la plus forte). Données : overview.radar (480 points) réduites ici.

import type { Vod } from "@/lib/api";
import { hm } from "@/lib/format";
import { cn } from "@/lib/utils";

export type ZoneState = "done" | "current" | "waiting";

const BARS = 160;
const LABEL_GAP = 1.8; // % de largeur sous lequel deux numéros se chevauchent : on décale le second d'une ligne

function reduce(values: number[], bars: number) {
  if (!values.length) return [];
  return Array.from({ length: bars }, (_, i) => {
    const a = Math.floor((i / bars) * values.length);
    const b = Math.max(a + 1, Math.floor(((i + 1) / bars) * values.length));
    return Math.max(...values.slice(a, b));
  });
}

/** Graduations « 0:00 1:00 2:00 … » : un pas qui donne au plus 8 repères, et la durée totale à droite. */
function ticks(duration: number) {
  const step = [300, 600, 1800, 3600, 7200].find((s) => duration / s <= 8) ?? 7200;
  const out: number[] = [];
  for (let t = 0; t < duration - step / 3; t += step) out.push(t);
  return [...out, duration];
}

const hmm = (s: number) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;

export function Radar({ vod, zoneState }: { vod: Vod; zoneState: (rank: number) => ZoneState }) {
  const chat = reduce(vod.radar.chat, BARS);
  const audio = reduce(vod.radar.audio, BARS);
  const hasChat = chat.some((v) => v > 0);
  const zones = [...vod.windows].sort((a, b) => a.start - b.start).map((w) => ({ ...w, left: (((w.start + w.end) / 2) / vod.duration) * 100 }));
  const lanes: number[] = [];
  const placed = zones.map((z) => {
    let lane = lanes.findIndex((last) => z.left - last >= LABEL_GAP);
    if (lane === -1) lane = lanes.length < 3 ? lanes.length : 0;
    lanes[lane] = z.left;
    return { ...z, lane };
  });
  const laneCount = Math.max(1, Math.min(3, lanes.length));

  return (
    <section className="card-qc mb-8 p-8">
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
        <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="title-lg">Radar du hype</span>
          <span className="text-muted-foreground">
            {vod.windows.length} zones repérées ·{" "}
            <span className="font-medium text-ink">{hm(vod.zones_seconds)} à traiter au lieu de {hm(vod.duration)}</span>
          </span>
        </p>
        <div className="flex gap-5 text-sm text-muted-foreground">
          {hasChat && <Legend className="bg-blue">Chat</Legend>}
          <Legend className="bg-[#bfc1cc]">Audio</Legend>
          <Legend className="bg-yellow">Zone repérée</Legend>
        </div>
      </div>

      <div className="relative" style={{ paddingTop: `${laneCount * 1.5}rem` }}>
        {placed.map((z) => {
          const state = zoneState(z.rank);
          return (
            <span key={z.rank} className={cn("absolute -translate-x-1/2 rounded px-1 font-mono text-[0.72rem]",
              state === "done" && "text-blue", state === "current" && "bg-yellow-soft font-semibold text-olive",
              state === "waiting" && "text-muted-foreground")}
                  style={{ left: `${z.left}%`, top: `${z.lane * 1.5}rem` }}>
              {String(z.rank).padStart(2, "0")}
            </span>
          );
        })}
        <div className="relative h-72" role="img" aria-label={`Activité du chat et volume sur ${hm(vod.duration)}, ${vod.windows.length} zones repérées`}>
          {placed.map((z) => (
            <span key={z.rank} className={cn("absolute inset-y-0 w-1.5 -translate-x-1/2 rounded-full",
              zoneState(z.rank) === "waiting" ? "bg-yellow/60" : "bg-yellow")} style={{ left: `${z.left}%` }} />
          ))}
          <div className="absolute inset-x-0 top-0 flex h-1/2 items-end gap-[3px]">
            {(hasChat ? chat : audio.map(() => 0)).map((v, i) => (
              <span key={i} className="flex-1 rounded-t-full bg-blue/55" style={{ height: `${Math.round(Math.max(0.04, v) * 60)}%` }} />
            ))}
          </div>
          <div className="absolute inset-x-0 bottom-0 flex h-1/2 items-start gap-[3px]">
            {audio.map((v, i) => (
              <span key={i} className="flex-1 rounded-b-full bg-[#bfc1cc]" style={{ height: `${Math.round(Math.max(0.04, v) * 40)}%` }} />
            ))}
          </div>
        </div>
        <div className="relative mt-6 h-5 font-mono text-sm text-muted-foreground">
          {ticks(vod.duration).map((t, i, all) => (
            <span key={t} className={cn("absolute", i === 0 ? "" : i === all.length - 1 ? "-translate-x-full" : "-translate-x-1/2")}
                  style={{ left: `${(t / vod.duration) * 100}%` }}>{hmm(t)}</span>
          ))}
        </div>
      </div>
      {!hasChat && <p className="mt-4 text-sm text-muted-foreground">Pas de replay de chat pour cette source : zones repérées au volume seul.</p>}
    </section>
  );
}

function Legend({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className="flex items-center gap-2"><span className={cn("size-3 rounded-[3px]", className)} />{children}</span>;
}
