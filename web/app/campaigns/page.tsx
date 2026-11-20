"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";

import { CampaignCard } from "@/components/campaign-card";
import { PageHeader } from "@/components/page-header";
import { ApiDown, EmptyCampaigns } from "@/components/states";
import { type CampaignSummary, api } from "@/lib/api";

export default function CampaignsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["campaigns"], queryFn: () => api<CampaignSummary[]>("/api/campaigns") });
  return (
    <>
      <PageHeader eyebrow="Campagnes" title="Campagnes">
        <Link href="/campaigns/new" className="flex h-12 items-center gap-2 rounded-2xl bg-yellow px-6 font-semibold">
          <Plus className="size-5" /> Nouvelle campagne
        </Link>
      </PageHeader>
      {error && <ApiDown message={error.message} />}
      {isLoading && <div className="card-qc h-64 animate-pulse" />}
      {data && !data.length && <EmptyCampaigns />}
      {!!data?.length && <div className="grid grid-cols-4 gap-6">{data.map((c) => <CampaignCard key={c.slug} c={c} />)}</div>}
    </>
  );
}
