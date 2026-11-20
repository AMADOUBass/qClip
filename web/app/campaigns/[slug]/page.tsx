"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { BriefFormView } from "@/components/brief-form";
import { ApiDown } from "@/components/states";
import { type BriefView, api } from "@/lib/api";

export default function CampaignPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data, error } = useQuery({ queryKey: ["campaign", slug], queryFn: () => api<BriefView>(`/api/campaigns/${slug}`) });
  if (error) return <ApiDown message={error.message} />;
  if (!data) return <div className="card-qc h-96 animate-pulse" />;
  // key : le formulaire repart des valeurs enregistrées quand on change de campagne
  return <BriefFormView key={slug} initial={data} slug={slug} />;
}
