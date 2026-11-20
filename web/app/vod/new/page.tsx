"use client";

// Nouvelle VOD : choisir la campagne (ou ?campaign=<slug> depuis le brief), relire sa règle de source,
// puis coller l'URL. On ne traite que du contenu rattaché à une campagne.

import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { ApiDown } from "@/components/states";
import { AnalyzeForm } from "@/components/vod/analyze-form";
import { type BriefView, type CampaignSummary, api } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function NewVodPage() {
  const params = useSearchParams();
  const { data: campaigns, error } = useQuery({ queryKey: ["campaigns"], queryFn: () => api<CampaignSummary[]>("/api/campaigns") });
  const [picked, setPicked] = useState<string | null>(params.get("campaign"));
  const slug = picked ?? (campaigns?.length === 1 ? campaigns[0].slug : null);
  const { data: brief } = useQuery({
    queryKey: ["campaign", slug],
    queryFn: () => api<BriefView>(`/api/campaigns/${slug}`),
    enabled: !!slug,
  });
  const [confirmed, setConfirmed] = useState<string | null>(null); // slug dont la règle a été confirmée
  const rule = brief?.brief.source_rule ?? "";
  const ok = !rule || confirmed === slug;

  if (error) return <ApiDown message={error.message} />;
  return (
    <>
      <PageHeader eyebrow="VOD / NOUVELLE" title="Nouvelle VOD" search={false}>
        <AnalyzeForm campaign={slug ?? undefined} disabledReason={ok ? undefined : "Confirme d'abord la règle de source"} />
      </PageHeader>

      <div className="grid max-w-5xl grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-6">
        <section className="card-qc p-8">
          <h2 className="title-lg mb-5">Campagne</h2>
          {campaigns?.length === 0 && (
            <p className="text-muted-foreground">
              Aucune campagne : <Link href="/campaigns/new" className="font-medium text-blue">crée d&apos;abord son brief</Link>.
            </p>
          )}
          <div className="space-y-3" role="radiogroup" aria-label="Campagne">
            {campaigns?.map((c) => (
              <button key={c.slug} type="button" role="radio" aria-checked={slug === c.slug} onClick={() => setPicked(c.slug)}
                      className={cn("flex w-full items-center gap-4 rounded-2xl border p-4 text-left transition-colors",
                        slug === c.slug ? "border-yellow bg-yellow-soft" : "border-line bg-secondary/60 hover:bg-secondary")}>
                <span className="grid size-11 shrink-0 place-items-center rounded-full bg-surface font-display font-bold text-olive">{c.initials}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{c.name}</span>
                  <span className="font-mono text-xs text-muted-foreground uppercase">
                    {[c.platform, c.language, c.test_only && "test"].filter(Boolean).join(" · ")}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className={cn("card-qc p-8", rule && !ok && "border-yellow")}>
          <h2 className="title-lg mb-5">Règle de source</h2>
          {!slug ? (
            <p className="text-muted-foreground">Choisis la campagne pour voir sa règle.</p>
          ) : rule ? (
            <>
              <p className="mb-6 rounded-2xl bg-yellow-soft p-4 text-lg font-medium text-olive">{rule}</p>
              <button type="button" role="checkbox" aria-checked={ok} onClick={() => setConfirmed(ok ? null : slug)}
                      className="flex w-full items-center gap-3 text-left">
                <span className={cn("grid size-6 shrink-0 place-items-center rounded-md border", ok ? "border-olive bg-olive text-white" : "border-line bg-surface")}>
                  {ok && <Check className="size-4" />}
                </span>
                Cette VOD respecte la règle
              </button>
            </>
          ) : (
            <p className="text-muted-foreground">Pas de règle particulière : toute VOD de {brief?.brief.creator || "ce créateur"} convient.</p>
          )}
          <p className="mt-6 text-sm text-muted-foreground">
            L&apos;URL est ajoutée aux sources du brief. qClip lit d&apos;abord le chat et le volume de toute la VOD, puis ne
            télécharge que les zones fortes.
          </p>
        </section>
      </div>
    </>
  );
}
