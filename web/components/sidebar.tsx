"use client";

// Barre latérale des maquettes : logo « qC », 6 sections, jauge CPU en bas.

import { useQuery } from "@tanstack/react-query";
import { Activity, Clapperboard, Columns3, Copy, Flag, LayoutGrid, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { type SystemStatus, api } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Accueil", icon: LayoutGrid },
  { href: "/campaigns", label: "Campagnes", icon: Flag },
  { href: "/vod", label: "VOD", icon: Activity },
  { href: "/sort", label: "Tri", icon: Copy },
  { href: "/editor", label: "Éditeur", icon: Clapperboard },
  { href: "/pipeline", label: "Pipeline", icon: Columns3 },
];

export function Sidebar() {
  const pathname = usePathname();
  const { data: system } = useQuery({
    queryKey: ["system"],
    queryFn: () => api<SystemStatus>("/api/system"),
    refetchInterval: 4000,
  });
  const cpu = Math.round(system?.cpu_percent ?? 0);

  return (
    <aside className="sticky top-0 flex h-screen w-[104px] shrink-0 flex-col items-center border-r border-line bg-surface py-6">
      <Link
        href="/"
        className="mb-6 grid size-14 place-items-center rounded-2xl bg-yellow font-display text-xl font-extrabold tracking-tight"
        aria-label="Accueil qClip"
      >
        qC
      </Link>
      <nav className="flex flex-col gap-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex w-[84px] flex-col items-center gap-1 rounded-2xl py-2.5 text-[0.8rem] text-muted-foreground transition-colors hover:text-ink",
                active && "bg-yellow font-semibold text-ink",
              )}
            >
              <Icon className="size-5" strokeWidth={1.8} />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto flex flex-col items-center gap-2" title={system ? `RAM ${system.ram_used_gb}/${system.ram_total_gb} Go` : ""}>
        <span className="eyebrow text-[0.65rem]">CPU</span>
        <div className="relative h-16 w-2 overflow-hidden rounded-full bg-secondary">
          <div className="absolute inset-x-0 bottom-0 rounded-full bg-blue transition-all" style={{ height: `${cpu}%` }} />
        </div>
        <span className="font-mono text-xs text-blue">{system ? `${cpu}%` : "—"}</span>
      </div>
    </aside>
  );
}
