"use client";

import { Plus } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Upcoming } from "@/components/upcoming";
import { greeting } from "@/lib/format";
import { useNow } from "@/lib/use-now";

export default function Home() {
  const now = useNow();
  const eyebrow = now
    ? now.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" }).replace(/\./g, "").toUpperCase()
    : " ";
  return (
    <>
      <PageHeader eyebrow={eyebrow} title={now ? `${greeting(now)}.` : " "}>
        <Link href="/vod/new" className="flex h-12 items-center gap-2 rounded-2xl bg-yellow px-6 font-semibold">
          <Plus className="size-5" /> Nouvelle VOD
        </Link>
      </PageHeader>
      <Upcoming screen="Tableau de bord" step={3} />
    </>
  );
}
