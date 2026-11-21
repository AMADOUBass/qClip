"use client";

// Tri des moments (maquette 4) : un moment à la fois, du plus fort au plus faible. Garder (A) / Rejeter (X) /
// Passer, J / K pour naviguer, Espace pour lire, [ ] pour poser le début / la fin à la tête de lecture.
// Les décisions et les bornes vont dans work/<id>/edits.json (PUT /api/vods/<id>/moments/<plage>).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Play, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { Bounds } from "@/components/sort/bounds";
import { API, type Moment, type Moments, type Peaks, api, post, put } from "@/lib/api";
import { clock, eta, score10, stamp } from "@/lib/format";
import { useUi } from "@/lib/store";
import { cn } from "@/lib/utils";

type Decision = NonNullable<Moment["decision"]>;

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/** « chat ×6.0 » → « Pic de chat ×6,0 », « rires (0.81) » → « Rires »… */
export function reasonLabel(reason: string) {
  const chat = /^chat ×([\d.]+)$/.exec(reason);
  if (chat) return `Pic de chat ×${chat[1].replace(".", ",")}`;
  const text = reason.replace(/\s*\([\d.]+\)$/, "");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function SortView({ data }: { data: Moments }) {
  const router = useRouter();
  const params = useSearchParams();
  const client = useQueryClient();
  const vid = data.video_id;
  const list = data.moments;
  const asked = Number(params.get("w"));
  const current = list.find((m) => m.window === asked) ?? list.find((m) => !m.decision) ?? list[0];
  const index = list.indexOf(current);

  const go = (m: Moment | undefined) => {
    if (m) router.replace(`/sort?vod=${vid}&w=${m.window}`, { scroll: false });
  };
  const nextOpen = (from: number) =>
    [...list.slice(from + 1), ...list.slice(0, from)].find((m) => !m.decision && m.window !== current.window);

  const decide = useMutation({
    mutationFn: ({ m, decision }: { m: Moment; decision: Decision }) =>
      put(`/api/vods/${vid}/moments/${m.window}`, { decision }),
    onMutate: ({ m, decision }) => {
      // Affichage immédiat : on avance sans attendre l'API.
      client.setQueryData<Moments>(["moments", vid], (old) => old && withDecision(old, m.window, decision));
      go(nextOpen(index) ?? m);
    },
    onError: (e) => {
      toast.error(e.message);
      client.invalidateQueries({ queryKey: ["moments", vid] });
    },
  });
  const bounds = useMutation({
    mutationFn: ({ m, start, end }: { m: Moment; start: number; end: number }) =>
      put(`/api/vods/${vid}/moments/${m.window}`, { start: m.window_start + start, end: m.window_start + end }),
    onMutate: ({ m, start, end }) =>
      client.setQueryData<Moments>(["moments", vid], (old) => old && {
        ...old,
        moments: old.moments.map((x) => x.window === m.window
          ? { ...x, start: m.window_start + start, end: m.window_start + end, duration: end - start, edited: true } : x),
      }),
    onSettled: () => client.invalidateQueries({ queryKey: ["moments", vid] }), // bornes recalées sur les mots
    onError: (e) => toast.error(e.message),
  });
  const render = useMutation({
    mutationFn: () => post(`/api/vods/${vid}/render`, { kept: true }),
    onSuccess: () => toast.success(`Rendu de ${data.kept} clip${data.kept > 1 ? "s" : ""} lancé`, {
      description: "Suivi dans la pastille en haut ; les clips arrivent dans le pipeline.",
    }),
    onError: (e) => toast.error(e.message),
  });
  const renderEstimate = list.filter((m) => m.decision === "keep").reduce((s, m) => s + m.duration * 0.7, 0);

  // Ctrl R (palette) arrive ici avec ?render=kept : on demande confirmation avant de lancer.
  const askedRender = params.get("render") === "kept";
  useEffect(() => {
    if (!askedRender) return;
    if (!data.kept) toast.info("Aucun moment gardé pour l'instant : garde-en avec A.");
    else toast(`Rendre les ${data.kept} moments gardés ?`, {
      description: `≈ ${Math.max(1, Math.round(renderEstimate / 60))} min de calcul (Intel Quick Sync)`,
      action: { label: "Lancer", onClick: () => render.mutate() },
    });
    router.replace(`/sort?vod=${vid}&w=${current.window}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- une seule fois par demande
  }, [askedRender]);

  return (
    <>
      <PageHeader
        eyebrow={`${data.campaign_name} — ${data.title} / Tri`}
        title={<>Moment {index + 1} <span className="text-muted-foreground/70">/ {list.length}</span></>}
        search={false}
      />
      <div className="grid grid-cols-[minmax(0,1fr)_26rem] gap-8">
        <MomentPanel key={current.window} vid={vid} m={current} minLen={data.min_len} maxLen={data.max_len}
                     onDecide={(decision) => decide.mutate({ m: current, decision })}
                     onBounds={(start, end) => bounds.mutate({ m: current, start, end })}
                     onPrev={() => go(list[index - 1])} onNext={() => go(list[index + 1])} />
        <aside className="space-y-8">
          <Progress data={data} current={current} onPick={go} renderEstimate={renderEstimate}
                    rendering={render.isPending} onRender={() => render.mutate()} />
          <Upcoming vid={vid} moments={[...list.slice(index + 1), ...list.slice(0, index)].filter((m) => !m.decision).slice(0, 4)} onPick={go} />
        </aside>
      </div>
    </>
  );
}

function withDecision(data: Moments, window: number, decision: Decision): Moments {
  const moments = data.moments.map((m) => (m.window === window ? { ...m, decision } : m));
  const kept = moments.filter((m) => m.decision === "keep").length;
  const rejected = moments.filter((m) => m.decision === "reject").length;
  return { ...data, moments, kept, rejected, remaining: moments.length - kept - rejected };
}

function MomentPanel({ vid, m, minLen, maxLen, onDecide, onBounds, onPrev, onNext }: {
  vid: string; m: Moment; minLen: number; maxLen: number;
  onDecide: (d: Decision) => void; onBounds: (start: number, end: number) => void; onPrev: () => void; onNext: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [playhead, setPlayhead] = useState(m.start - m.window_start);
  // Bornes : celles des données (recalées sur les mots par l'API), sauf pendant qu'on tire une poignée.
  const [drag, setDrag] = useState<[number, number] | null>(null);
  const [start, end] = drag ?? [m.start - m.window_start, m.end - m.window_start];
  const { data: peaks } = useQuery({
    queryKey: ["peaks", vid, m.window],
    queryFn: () => api<Peaks>(`/api/vods/${vid}/moments/${m.window}/peaks`),
    staleTime: Infinity,
  });
  const fileDuration = peaks?.duration ?? m.window_duration ?? m.end - m.window_start + 5;

  const seek = (t: number) => {
    if (video.current) video.current.currentTime = t;
    setPlayhead(t);
  };
  const toggle = () => {
    const v = video.current;
    if (!v) return;
    if (!v.paused) return v.pause();
    if (v.currentTime < start || v.currentTime >= end - 0.05) v.currentTime = start;
    v.play().catch(() => toast.error("Lecture impossible : la vidéo de la plage ne se charge pas"));
  };
  const commit = (s: number, e: number) => {
    setDrag(null);
    onBounds(s, e);
  };

  // Raccourcis du tri (pas pendant la saisie ni avec la palette ouverte).
  const onKey = useEffectEvent((e: KeyboardEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target) || useUi.getState().paletteOpen) return;
    const k = e.key.toLowerCase();
    if (k === "a") onDecide("keep");
    else if (k === "x") onDecide("reject");
    else if (k === "j") onPrev();
    else if (k === "k") onNext();
    else if (k === " ") toggle();
    else if (k === "[" && playhead < end - minLen) commit(Math.max(playhead, end - maxLen), end);
    else if (k === "]" && playhead > start + minLen) commit(start, Math.min(playhead, start + maxLen));
    else return;
    e.preventDefault();
  });
  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKey(e);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  return (
    <div className="min-w-0">
      <div className="relative mb-6 aspect-video overflow-hidden rounded-[1.75rem] bg-ink">
        <video ref={video} src={`${API}/media/${m.video}`} preload="metadata" playsInline className="size-full object-contain"
               onLoadedMetadata={(e) => { e.currentTarget.currentTime = start; }}
               onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
               onTimeUpdate={(e) => {
                 const t = e.currentTarget.currentTime;
                 setPlayhead(t);
                 if (t >= end) { e.currentTarget.pause(); e.currentTarget.currentTime = start; }
               }} />
        <div className="absolute top-6 left-6 rounded-2xl bg-yellow px-4 py-2.5">
          <p className="font-mono text-[0.72rem] tracking-[0.14em] uppercase">Score</p>
          <p className="font-display text-4xl leading-none font-extrabold">{score10(m.score)}</p>
        </div>
        {!playing && (
          <button type="button" onClick={toggle} aria-label="Lire le moment"
                  className="absolute top-1/2 left-1/2 grid size-20 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-ink/90 text-yellow">
            <Play className="size-8 translate-x-0.5 fill-current" />
          </button>
        )}
        <div className="absolute bottom-6 left-6 flex gap-2 font-mono">
          <span className="rounded-lg bg-ink/85 px-3 py-1.5 text-white">{stamp(m.window_start + start)}</span>
          <span className="rounded-lg bg-ink/85 px-3 py-1.5 text-yellow">{clock(end - start)}</span>
        </div>
        {m.decision && (
          <span className={cn("absolute top-6 right-6 rounded-xl px-3 py-1.5 font-mono text-sm uppercase",
            m.decision === "keep" ? "bg-yellow text-ink" : m.decision === "reject" ? "bg-pink text-white" : "bg-secondary text-ink")}>
            {m.decision === "keep" ? "Gardé" : m.decision === "reject" ? "Rejeté" : "Passé"}
          </span>
        )}
      </div>

      <Bounds peaks={peaks?.peaks ?? []} duration={fileDuration} start={start} end={end} playhead={playhead}
              minLen={minLen} maxLen={maxLen} offset={m.window_start}
              onChange={(s, e) => setDrag([s, e])} onCommit={commit} onSeek={seek} />

      <div className="mt-6 mb-5 flex flex-wrap gap-2">
        {m.reasons.map((r) => <span key={r} className="rounded-full bg-blue-soft px-4 py-1.5 font-medium text-blue">{reasonLabel(r)}</span>)}
        {m.edited && <span className="rounded-full bg-secondary px-4 py-1.5 text-muted-foreground">Bornes ajustées</span>}
      </div>
      {m.text && <p className="mb-7 line-clamp-3 text-[1.35rem] leading-snug">« {m.text} »</p>}

      <div className="grid grid-cols-[1fr_auto_1.35fr] gap-4">
        <button type="button" onClick={() => onDecide("reject")}
                className="flex h-16 items-center justify-center gap-3 rounded-2xl border border-pink/40 bg-pink-soft text-lg font-semibold text-pink">
          <X className="size-5" /> Rejeter <span className="kbd bg-pink/15 text-pink">X</span>
        </button>
        <button type="button" onClick={() => onDecide("skip")}
                className="h-16 rounded-2xl border border-line bg-surface px-14 text-lg font-medium text-muted-foreground">Passer</button>
        <button type="button" onClick={() => onDecide("keep")}
                className="flex h-16 items-center justify-center gap-3 rounded-2xl bg-yellow text-lg font-semibold">
          <Check className="size-5" /> Garder <span className="kbd bg-ink/10">A</span>
        </button>
      </div>
      <p className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-muted-foreground">
        <span><span className="kbd">J</span> / <span className="kbd">K</span> moment précédent / suivant</span>
        <span><span className="kbd">Espace</span> lire</span>
        <span><span className="kbd">[</span> <span className="kbd">]</span> début / fin</span>
      </p>
    </div>
  );
}

function Progress({ data, current, onPick, renderEstimate, rendering, onRender }: {
  data: Moments; current: Moment; onPick: (m: Moment) => void; renderEstimate: number; rendering: boolean; onRender: () => void;
}) {
  const done = data.remaining === 0 || data.moments.every((m) => m.decision);
  return (
    <div className="card-qc p-7">
      <p className="eyebrow mb-3">Progression</p>
      <p className="mb-4 flex items-baseline gap-3">
        <span className="font-display text-6xl leading-none font-extrabold text-olive">{data.kept}</span>
        <span className="text-lg text-muted-foreground">gardés / {data.moments.length}</span>
      </p>
      <div className="mb-3 flex gap-1">
        {data.moments.map((m) => (
          <button key={m.window} type="button" onClick={() => onPick(m)} aria-label={`Moment ${m.window}`}
                  className={cn("h-8 flex-1 rounded-full",
                    m.decision === "keep" ? "bg-yellow" : m.decision === "reject" ? "bg-[#f4b9c8]" : m.decision === "skip" ? "bg-[#d8d5cd]" : "bg-secondary",
                    m.window === current.window && "ring-2 ring-blue ring-offset-1")} />
        ))}
      </div>
      <div className="flex justify-between text-muted-foreground">
        <span>{data.rejected} rejeté{data.rejected > 1 ? "s" : ""}</span>
        <span>{data.remaining} restant{data.remaining > 1 ? "s" : ""}</span>
      </div>
      {data.kept > 0 && (
        <button type="button" onClick={onRender} disabled={rendering}
                className={cn("mt-6 h-13 w-full rounded-2xl font-semibold disabled:opacity-60",
                  done ? "bg-yellow" : "border border-line bg-secondary")}>
          {data.kept > 1 ? `Rendre les ${data.kept} moments gardés` : "Rendre le moment gardé"} · {eta(renderEstimate)}
        </button>
      )}
      {done && <p className="mt-3 text-center text-sm text-muted-foreground">Tri terminé · <span className="kbd">Ctrl R</span> lance aussi le rendu</p>}
    </div>
  );
}

function Upcoming({ vid, moments, onPick }: { vid: string; moments: Moment[]; onPick: (m: Moment) => void }) {
  if (!moments.length) return null;
  return (
    <div>
      <p className="eyebrow mb-4">Ensuite</p>
      <div className="space-y-3">
        {moments.map((m) => (
          <button key={m.window} type="button" onClick={() => onPick(m)}
                  className="card-qc flex w-full items-center gap-4 p-3 text-left transition-shadow hover:shadow-md">
            <span className="relative h-16 w-28 shrink-0 overflow-hidden rounded-xl bg-ink">
              {/* eslint-disable-next-line @next/next/no-img-element -- image locale servie par l'API */}
              <img src={`${API}/api/vods/${vid}/moments/${m.window}/frame`} alt="" loading="lazy" className="size-full object-cover" />
              <span className="absolute right-1.5 bottom-1.5 rounded bg-ink/85 px-1.5 font-mono text-xs text-white">{clock(m.duration)}</span>
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold">{m.hook || firstWords(m.text)}</span>
              <span className="block truncate font-mono text-sm text-muted-foreground">
                {stamp(m.start)}{m.reasons[0] ? ` · ${reasonLabel(m.reasons[0])}` : ""}
              </span>
            </span>
            <span className="font-display text-2xl font-bold text-olive">{score10(m.score)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const firstWords = (text: string) => {
  const words = text.split(/\s+/).filter(Boolean);
  return words.length > 7 ? `${words.slice(0, 7).join(" ")}…` : text || "Sans paroles";
};

/** Rien à trier : pas encore de VOD analysée, ou analyse pas terminée. */
export function NothingToSort({ vid }: { vid?: string }) {
  return (
    <>
      <PageHeader eyebrow="Tri" title="Tri des moments" />
      <div className="card-qc max-w-2xl p-8">
        <h2 className="title-lg mb-3">{vid ? "Moments pas encore prêts" : "Rien à trier"}</h2>
        <p className="mb-6 text-muted-foreground">
          {vid ? "Les moments apparaissent ici à la fin de l'analyse (détection des moments)."
            : "Analyse d'abord une VOD de campagne : ses moments forts arrivent ici, les meilleurs d'abord."}
        </p>
        <Link href={vid ? `/vod/${vid}` : "/vod/new"} className="inline-flex h-12 items-center rounded-2xl bg-yellow px-6 font-semibold">
          {vid ? "Voir l'analyse" : "Analyser une VOD"}
        </Link>
      </div>
    </>
  );
}
