"use client";

// Pastille de l'en-tête : « ● Séparation de la voix · 14/24 ≈ 19 min » (tâche en cours, en direct).

import Link from "next/link";

import { useCurrentJob } from "@/lib/events";
import { eta } from "@/lib/format";

export function JobPill() {
  const job = useCurrentJob();
  if (!job) return null;
  const label = job.status === "queued" ? "En attente" : job.stage ? capitalize(job.stage) : job.label;
  const href = job.video_id ? `/vod/${job.video_id}` : "/vod";
  return (
    <Link
      href={href}
      className="flex h-12 items-center gap-3 rounded-full border border-blue/40 bg-surface px-5 text-[0.95rem] transition-colors hover:bg-blue-soft"
    >
      <span className="size-2.5 animate-pulse rounded-full bg-blue" />
      <span>
        {label}
        {job.progress ? ` · ${job.progress[0]}/${job.progress[1]}` : ""}
      </span>
      {job.eta_s != null && <span className="font-mono text-sm text-blue">{eta(job.eta_s)}</span>}
    </Link>
  );
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
