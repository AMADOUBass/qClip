// Vignette verticale « Derniers clips » (maquette 1) : miniature, badge de statut, accroche par-dessus.

import type { PipelineItem } from "@/lib/api";
import { media } from "@/lib/api";
import { clock, compact } from "@/lib/format";
import { cn } from "@/lib/utils";

export const STATUS: Record<PipelineItem["status"], { label: string; className: string }> = {
  paye: { label: "PAYÉ", className: "bg-yellow text-ink" },
  poste: { label: "POSTÉ", className: "bg-blue text-white" },
  rendu: { label: "RENDU", className: "bg-white text-ink" },
  a_revoir: { label: "À VÉRIFIER", className: "bg-orange text-ink" },
};

export function ClipThumb({ clip }: { clip: PipelineItem }) {
  const status = STATUS[clip.status];
  return (
    <figure className="w-full">
      <div className="relative aspect-[9/16] overflow-hidden rounded-[1.4rem] bg-ink">
        {/* eslint-disable-next-line @next/next/no-img-element -- fichier local servi par l'API */}
        <img src={media(clip.thumbnail)} alt="" className="absolute inset-0 size-full object-cover opacity-80" loading="lazy" />
        <div className="absolute inset-0 bg-gradient-to-b from-ink/10 via-ink/30 to-ink/70" />
        <span className={cn("absolute top-3 left-3 rounded-md px-2 py-0.5 font-mono text-[0.68rem] font-bold", status.className)}>
          {status.label}
        </span>
        {clip.hook && (
          <p className="absolute inset-x-3 top-1/2 -translate-y-1/2 text-center font-display text-[0.95rem] leading-tight font-extrabold text-white uppercase drop-shadow">
            {clip.hook}
          </p>
        )}
      </div>
      <figcaption className="mt-3">
        <p className="font-medium">{clip.creator}</p>
        <p className="font-mono text-sm text-muted-foreground">
          {clip.duration ? clock(clip.duration) : "—"} · {clip.views ? compact(clip.views) : clip.status === "rendu" ? "prêt" : "—"}
        </p>
      </figcaption>
    </figure>
  );
}
