"use client";

// Éditeur : ?vod=<id>&w=<plage>. Sans paramètres : premier clip gardé de la dernière VOD (sinon son meilleur moment).

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import { EditorView } from "@/components/editor/editor-view";
import { NothingToSort } from "@/components/sort/sort-view";
import { ApiDown } from "@/components/states";
import { ApiError, type EditorData, type Moments, type VodItem, api } from "@/lib/api";

export default function EditorPage() {
  const params = useSearchParams();
  const { data: vods, error: vodsError } = useQuery({
    queryKey: ["vods"],
    queryFn: () => api<VodItem[]>("/api/vods"),
    enabled: !params.get("vod"),
  });
  const vid = params.get("vod") ?? vods?.[0]?.video_id;
  const { data: moments, error } = useQuery({
    queryKey: ["moments", vid],
    queryFn: () => api<Moments>(`/api/vods/${vid}/moments`),
    enabled: !!vid,
    retry: false,
  });
  const asked = Number(params.get("w"));
  const window = moments?.moments.find((m) => m.window === asked)?.window
    ?? moments?.moments.find((m) => m.decision === "keep")?.window ?? moments?.moments[0]?.window;
  const { data, error: editorError } = useQuery({
    queryKey: ["editor", vid, window],
    queryFn: () => api<EditorData>(`/api/vods/${vid}/moments/${window}/editor`),
    enabled: !!vid && window != null,
    retry: false,
  });

  const failure = vodsError ?? error ?? editorError;
  if (failure) return failure instanceof ApiError && failure.status === 404 ? <NothingToSort vid={vid} /> : <ApiDown message={failure.message} />;
  if (vods && !vid) return <NothingToSort />;
  if (!data || !moments) return <div className="card-qc h-96 animate-pulse" />;
  // key : l'accroche saisie repart de la valeur enregistrée quand on change de clip
  return <EditorView key={`${vid}-${data.window}`} data={data} moments={moments} />;
}
