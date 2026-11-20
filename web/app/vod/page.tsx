"use client";

// « VOD » dans la barre latérale : l'analyse en cours s'il y en a une, sinon la dernière VOD repérée.

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { ApiDown } from "@/components/states";
import { Scouting, VodView } from "@/components/vod/vod-view";
import { type VodItem, api } from "@/lib/api";
import { useJobs } from "@/lib/events";

export default function VodIndexPage() {
  const { data: jobs } = useJobs();
  const { data: vods, error } = useQuery({ queryKey: ["vods"], queryFn: () => api<VodItem[]>("/api/vods") });
  const active = jobs?.find((j) => j.kind === "process" && (j.status === "running" || j.status === "queued"));
  if (error) return <ApiDown message={error.message} />;
  if (active && !active.video_id) return <Scouting job={active} />; // l'identifiant arrive avec les métadonnées
  const vid = active?.video_id ?? vods?.[0]?.video_id;
  if (vid) return <VodView key={vid} vid={vid} />;
  if (!vods) return <div className="card-qc h-96 animate-pulse" />;
  return (
    <>
      <PageHeader eyebrow="VOD" title="VOD" />
      <div className="card-qc max-w-2xl p-8">
        <h2 className="title-lg mb-3">Aucune VOD analysée</h2>
        <p className="mb-6 text-muted-foreground">Colle l&apos;URL d&apos;une VOD autorisée par une de tes campagnes : qClip repère les moments forts.</p>
        <Link href="/vod/new" className="inline-flex h-12 items-center rounded-2xl bg-yellow px-6 font-semibold">Analyser une VOD</Link>
      </div>
    </>
  );
}
