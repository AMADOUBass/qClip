"use client";

// En-tête commun : fil d'Ariane en capitales mono, grand titre (+ pastilles d'infos dessous), et à droite
// la tâche en cours, la recherche (Ctrl K) et l'action principale de l'écran.

import { Search } from "lucide-react";

import { JobPill } from "@/components/job-pill";
import { useUi } from "@/lib/store";

export function PageHeader({
  eyebrow,
  title,
  meta,
  children,
  search = true,
  job = true,
}: {
  eyebrow: string;
  title: React.ReactNode;
  meta?: React.ReactNode;
  children?: React.ReactNode;
  search?: boolean;
  job?: boolean;
}) {
  const open = useUi((s) => s.setPaletteOpen);
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-6">
      <div className="min-w-0">
        <p className="eyebrow mb-3">{eyebrow}</p>
        <h1 className="title-xl">{title}</h1>
        {meta && <div className="mt-4 flex flex-wrap items-center gap-2">{meta}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {job && <JobPill />}
        {search && (
          <button
            type="button"
            onClick={() => open(true)}
            className="flex h-12 items-center gap-3 rounded-2xl border border-line bg-surface px-4 text-muted-foreground transition-colors hover:text-ink"
          >
            <Search className="size-4" />
            Rechercher
            <span className="kbd">Ctrl K</span>
          </button>
        )}
        {children}
      </div>
    </header>
  );
}

/** Pastille d'info sous le titre : « KICK », « 6 H 12 MIN », « 48 213 MESSAGES ». */
export function MetaChip({ children }: { children: React.ReactNode }) {
  return <span className="rounded-lg bg-secondary px-3 py-1.5 font-mono text-[0.8rem] text-muted-foreground uppercase">{children}</span>;
}
