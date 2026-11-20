"use client";

// Tableau de bord (maquette 1).

import { useQuery } from "@tanstack/react-query";
import { Plus, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { CampaignCard } from "@/components/campaign-card";
import { ClipThumb } from "@/components/clip-thumb";
import { PageHeader } from "@/components/page-header";
import { RunningCard } from "@/components/running-card";
import { Sparkline } from "@/components/sparkline";
import { ApiDown, EmptyCampaigns } from "@/components/states";
import { type Dashboard, api } from "@/lib/api";
import { compact, greeting, money } from "@/lib/format";
import { useNow } from "@/lib/use-now";

export default function Home() {
  const now = useNow();
  const { data, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/dashboard") });
  const eyebrow = now
    ? now.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" }).replace(/\./g, "").toUpperCase()
    : " ";

  return (
    <>
      <PageHeader eyebrow={eyebrow} title={now ? `${greeting(now)}.` : " "}>
        <Link href="/vod/new" className="flex h-12 items-center gap-2 rounded-2xl bg-yellow px-6 font-semibold">
          <Plus className="size-5" /> Nouvelle VOD
        </Link>
      </PageHeader>

      {error && <ApiDown message={error.message} />}
      {isLoading && <div className="card-qc h-64 animate-pulse" />}
      {data && !data.campaigns.length && <EmptyCampaigns />}
      {data && !!data.campaigns.length && (
        <>
          <section className="mb-10 grid grid-cols-[1.35fr_1fr_1fr_1fr] gap-6">
            <div className="rounded-[1.75rem] bg-yellow p-8">
              <p className="mb-3 font-mono text-[0.78rem] tracking-[0.14em] uppercase">Gains · 7 jours</p>
              <div className="flex items-end justify-between gap-4">
                <p className="font-display text-[clamp(2.2rem,3.4vw,3.4rem)] leading-[0.95] font-extrabold whitespace-nowrap">{money(data.paid_7d)}</p>
                <Sparkline values={data.paid_series} className="h-12 w-28 min-w-0 shrink text-ink" />
              </div>
              <p className="mt-6 font-medium">
                +{money(data.paid_today)} aujourd&apos;hui · {data.paid_clips_7d} clip{data.paid_clips_7d > 1 ? "s" : ""} payé{data.paid_clips_7d > 1 ? "s" : ""}
              </p>
            </div>
            <Kpi label="Vues vérifiées" value={compact(data.views)}>
              <Sparkline values={data.views_series} className="mt-4 h-10 w-full text-blue" />
            </Kpi>
            <Kpi label="Moments à trier" value={String(data.to_sort)}>
              <Link href="/sort" className="mt-4 inline-block font-medium text-olive">Ouvrir le tri →</Link>
            </Kpi>
            <Kpi label="Prêts à poster" value={String(data.ready)}>
              {data.to_check > 0 && (
                <Link href="/pipeline" className="mt-4 flex items-center gap-2 font-medium text-orange">
                  <TriangleAlert className="size-4" /> {data.to_check} à vérifier
                </Link>
              )}
            </Kpi>
          </section>

          <RunningCard />

          <section className="mb-10">
            <div className="mb-5 flex items-end justify-between">
              <h2 className="title-lg">Campagnes actives</h2>
              <Link href="/campaigns/new" className="font-medium text-blue">+ Nouvelle campagne</Link>
            </div>
            <div className="grid grid-cols-4 gap-6">
              {data.campaigns.map((c) => <CampaignCard key={c.slug} c={c} />)}
            </div>
          </section>

          {!!data.recent_clips.length && (
            <section>
              <div className="mb-5 flex items-end justify-between">
                <h2 className="title-lg">Derniers clips</h2>
                <Link href="/pipeline" className="font-medium text-blue">Voir le pipeline →</Link>
              </div>
              <div className="grid grid-cols-7 gap-5">
                {data.recent_clips.map((clip) => <ClipThumb key={`${clip.video_id}-${clip.clip_id}`} clip={clip} />)}
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}

function Kpi({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <div className="card-qc p-8">
      <p className="eyebrow mb-3">{label}</p>
      <p className="font-display text-[3.2rem] leading-none font-bold">{value}</p>
      {children}
    </div>
  );
}
