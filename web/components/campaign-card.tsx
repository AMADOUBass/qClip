// Carte « Campagnes actives » (maquette 1) : tarif, plafond par clip, budget restant, alerte, clips / vues / gains.

import { TriangleAlert } from "lucide-react";
import Link from "next/link";

import type { CampaignSummary } from "@/lib/api";
import { compact, money } from "@/lib/format";
import { cn } from "@/lib/utils";

export function CampaignCard({ c }: { c: CampaignSummary }) {
  const hasBudget = c.budget_total != null && c.budget_left != null;
  const left = hasBudget ? Math.max(0, (c.budget_left as number) / (c.budget_total as number)) : 1;
  const chips = [c.platform?.toUpperCase(), c.language.toUpperCase(), c.test_only ? "TEST" : null].filter(Boolean);
  return (
    <Link href={`/campaigns/${c.slug}`} className="card-qc flex flex-col p-7 transition-shadow hover:shadow-md">
      <div className="mb-5 flex items-start gap-4">
        <span className="grid size-14 shrink-0 place-items-center rounded-full bg-secondary font-display text-lg font-bold text-olive">
          {c.initials}
        </span>
        <div className="min-w-0">
          <p className="truncate text-[1.15rem] font-medium">{c.name}</p>
          <div className="mt-1 flex gap-1.5">
            {chips.map((chip) => (
              <span key={chip} className="rounded-md bg-secondary px-2 py-0.5 font-mono text-[0.7rem] text-muted-foreground">
                {chip}
              </span>
            ))}
          </div>
        </div>
      </div>
      <p className="font-display text-[2.1rem] font-bold leading-none">
        {money(c.rate_per_1k)} <span className="font-sans text-base font-normal text-muted-foreground">/ 1 000 vues</span>
      </p>
      <p className="mt-4 font-mono text-sm text-muted-foreground">
        {c.payout_min != null || c.payout_max != null
          ? [c.payout_min != null && `Min ${c.payout_min} $`, c.payout_max != null && `Max ${c.payout_max} $`].filter(Boolean).join(" · ") + " par clip"
          : "Plafond par clip : voir le brief"}
      </p>
      <div className="mt-5 flex justify-between text-sm">
        <span className="text-muted-foreground">Budget restant</span>
        <span className="font-mono">{hasBudget ? `${c.budget_left} $ / ${c.budget_total} $` : "—"}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary">
        {hasBudget && (
          <div className={cn("h-full rounded-full", c.warning ? "bg-orange" : "bg-yellow")} style={{ width: `${left * 100}%` }} />
        )}
      </div>
      <div className="mt-4 min-h-12">
        {c.warning && (
          <p className="flex items-center gap-2 rounded-xl bg-orange-soft px-3 py-2 text-sm text-orange">
            <TriangleAlert className="size-4" /> {c.warning}
          </p>
        )}
        {!c.warning && c.note && <p className="rounded-xl bg-blue-soft px-3 py-2 text-sm text-blue">{c.note}</p>}
      </div>
      <dl className="mt-auto grid grid-cols-3 border-t border-line pt-4 text-sm">
        <Stat label="Clips" value={String(c.clips)} />
        <Stat label="Vues" value={c.views ? compact(c.views) : "—"} />
        <Stat label="Gains" value={c.earnings ? money(c.earnings) : "—"} olive />
      </dl>
    </Link>
  );
}

function Stat({ label, value, olive }: { label: string; value: string; olive?: boolean }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("mt-1 font-mono text-lg", olive && "text-olive")}>{value}</dd>
    </div>
  );
}
