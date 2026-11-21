"use client";

// Tri : ?vod=<id> (depuis l'écran VOD), sinon la dernière VOD repérée. ?w=<plage> ouvre un moment précis.

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import { NothingToSort, SortView } from "@/components/sort/sort-view";
import { ApiDown } from "@/components/states";
import { ApiError, type Moments, type VodItem, api } from "@/lib/api";

export default function SortPage() {
  const params = useSearchParams();
  const { data: vods, error: vodsError } = useQuery({
    queryKey: ["vods"],
    queryFn: () => api<VodItem[]>("/api/vods"),
    enabled: !params.get("vod"),
  });
  const vid = params.get("vod") ?? vods?.[0]?.video_id;
  const { data, error } = useQuery({
    queryKey: ["moments", vid],
    queryFn: () => api<Moments>(`/api/vods/${vid}/moments`),
    enabled: !!vid,
    retry: false,
  });

  if (vodsError) return <ApiDown message={vodsError.message} />;
  if (error) return error instanceof ApiError && error.status === 404 ? <NothingToSort vid={vid} /> : <ApiDown message={error.message} />;
  if (vods && !vid) return <NothingToSort />;
  if (!data) return <div className="card-qc h-96 animate-pulse" />;
  if (!data.moments.length) return <NothingToSort vid={vid} />;
  return <SortView data={data} />;
}
