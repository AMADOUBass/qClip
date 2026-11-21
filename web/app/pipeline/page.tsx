"use client";

// Pipeline des clips (maquette 6) : à revoir → rendu → posté → payé, filtrable par campagne.
// Les statuts viennent de posts.csv et de la conformité au brief (qclip/overview.py · pipeline).

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { ClipCard } from "@/components/pipeline/clip-card";
import { ApiDown } from "@/components/states";
import { type Pipeline, type PipelineItem, api } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";

const COLUMNS: { status: PipelineItem["status"]; label: string; dot: string }[] = [
  { status: "a_revoir", label: "À revoir", dot: "bg-orange" },
  { status: "rendu", label: "Rendu", dot: "bg-[#5b5d66]" },
  { status: "poste", label: "Posté", dot: "bg-blue" },
];

export default function PipelinePage() {
  const { data, error } = useQuery({ queryKey: ["clips"], queryFn: () => api<Pipeline>("/api/clips") });
  const [campaign, setCampaign] = useState<string | null>(null);
  if (error) return <ApiDown message={error.message} />;

  const campaigns = [...new Map((data?.items ?? []).map((c) => [c.campaign, c.campaign_name])).entries()];
  const items = (data?.items ?? []).filter((c) => !campaign || c.campaign === campaign);
  const of = (s: PipelineItem["status"]) => items.filter((c) => c.status === s);

  return (
    <>
      <PageHeader eyebrow="Tous les clips" title="Pipeline" search={false}>
        <div className="flex gap-10">
          <Total label="Payé cette semaine" value={data ? money(data.paid_week) : "—"} olive />
          <Total label="En attente" value={data ? money(data.pending) : "—"} />
        </div>
      </PageHeader>

      {campaigns.length > 1 && (
        <div className="mb-8 flex flex-wrap gap-2" role="tablist" aria-label="Campagne">
          {[[null, "Toutes"] as const, ...campaigns].map(([slug, name]) => (
            <button key={slug ?? "all"} type="button" role="tab" aria-selected={campaign === slug} onClick={() => setCampaign(slug)}
                    className={cn("h-11 rounded-full border px-5 font-medium", campaign === slug ? "border-ink bg-ink text-white" : "border-line bg-surface")}>
              {name}
            </button>
          ))}
        </div>
      )}

      {!data ? (
        <div className="card-qc h-96 animate-pulse" />
      ) : !data.items.length ? (
        <div className="card-qc max-w-2xl p-8">
          <h2 className="title-lg mb-3">Aucun clip rendu</h2>
          <p className="mb-6 text-muted-foreground">Trie les moments d&apos;une VOD, garde les meilleurs et lance le rendu : les clips arrivent ici.</p>
          <Link href="/sort" className="inline-flex h-12 items-center rounded-2xl bg-yellow px-6 font-semibold">Trier des moments</Link>
        </div>
      ) : (
        <>
          <div className="mb-8 grid grid-cols-3 items-start gap-6">
            {COLUMNS.map((col) => <Column key={col.status} label={col.label} dot={col.dot} clips={of(col.status)} />)}
          </div>
          <Column label="Payé" dot="bg-yellow" clips={of("paye")} wide />
        </>
      )}
    </>
  );
}

function Column({ label, dot, clips, wide }: { label: string; dot: string; clips: PipelineItem[]; wide?: boolean }) {
  return (
    <section className="rounded-[1.75rem] bg-secondary/70 p-4" aria-label={label}>
      <h2 className="mb-4 flex items-center gap-3 px-2 pt-1">
        <span className={cn("size-3 rounded-[3px]", dot)} />
        <span className="font-display text-lg font-bold">{label}</span>
        <span className="ml-auto font-mono text-sm text-muted-foreground">{clips.length}</span>
      </h2>
      <div className="space-y-4">
        {clips.map((c) => <ClipCard key={`${c.campaign}-${c.video_id}-${c.clip_id}`} clip={c} wide={wide} />)}
        {!clips.length && <p className="px-2 pb-2 text-sm text-muted-foreground">Aucun clip</p>}
      </div>
    </section>
  );
}

function Total({ label, value, olive }: { label: string; value: string; olive?: boolean }) {
  return (
    <div>
      <p className="eyebrow mb-1">{label}</p>
      <p className={cn("font-display text-4xl font-extrabold", olive && "text-olive")}>{value}</p>
    </div>
  );
}
