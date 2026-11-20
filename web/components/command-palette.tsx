"use client";

// Palette de commandes (maquette 8) : Ctrl K partout. Raccourcis globaux aussi hors palette :
// Ctrl N nouvelle VOD, T trier, Ctrl R rendre les clips gardés, Ctrl Shift C copier la dernière légende.

import { useQuery } from "@tanstack/react-query";
import { Copy, Play, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";
import { toast } from "sonner";

import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { type Dashboard, api } from "@/lib/api";
import { money } from "@/lib/format";
import { useUi } from "@/lib/store";

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

export function CommandPalette() {
  const router = useRouter();
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const { data } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/dashboard") });

  const run = useCallback(
    (action: "vod" | "sort" | "render" | "copy" | `campaign:${string}`) => {
      setOpen(false);
      if (action === "vod") router.push("/vod/new");
      else if (action === "sort") router.push("/sort");
      else if (action === "render") router.push("/sort?render=kept");
      else if (action === "copy") {
        const last = data?.recent_clips[0];
        if (!last?.caption) return toast.info("Aucun clip rendu pour l'instant");
        navigator.clipboard.writeText(last.caption).then(
          () => toast.success(`Légende copiée · ${last.title}`),
          () => toast.error("Copie impossible (permission du navigateur)"),
        );
      } else router.push(`/campaigns/${action.slice("campaign:".length)}`);
    },
    [data, router, setOpen],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!useUi.getState().paletteOpen);
      } else if (ctrl && e.shiftKey && e.key.toLowerCase() === "c") {
        e.preventDefault();
        run("copy");
      } else if (ctrl && !e.shiftKey && e.key.toLowerCase() === "n") {
        e.preventDefault();
        run("vod");
      } else if (ctrl && !e.shiftKey && e.key.toLowerCase() === "r") {
        e.preventDefault();
        run("render");
      } else if (!ctrl && !e.altKey && e.key.toLowerCase() === "t" && !isTyping(e.target) && !useUi.getState().paletteOpen) {
        run("sort");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, setOpen]);

  const last = data?.recent_clips[0];
  return (
    <CommandDialog open={open} onOpenChange={setOpen} title="Palette de commandes" className="max-w-2xl! rounded-[1.75rem]!">
      <Command className="bg-surface">
        <div className="relative">
          <CommandInput placeholder="Une action, une campagne, un clip…" className="h-14 text-base" />
          <span className="kbd absolute top-1/2 right-4 -translate-y-1/2">Échap</span>
        </div>
        <CommandList className="max-h-[60vh]">
          <CommandEmpty>Rien ne correspond.</CommandEmpty>
          <CommandGroup heading="Actions">
            <Item icon={<Plus />} accent title="Nouvelle VOD" detail="Coller l'URL d'un stream" keys="Ctrl N" onSelect={() => run("vod")} />
            <Item icon={<span className="font-display text-blue">A</span>} title="Trier les moments"
                  detail={`${data?.to_sort ?? 0} moments en attente`} keys="T" onSelect={() => run("sort")} />
            <Item icon={<Play className="text-blue" />} title="Rendre les clips gardés"
                  detail="Intel Quick Sync" keys="Ctrl R" onSelect={() => run("render")} />
            <Item icon={<Copy className="text-blue" />} title="Copier la légende du dernier clip"
                  detail={last ? `${last.title} · ${last.creator}` : "aucun clip rendu"} keys="Ctrl ⇧ C" onSelect={() => run("copy")} />
          </CommandGroup>
          {!!data?.campaigns.length && (
            <CommandGroup heading="Campagnes">
              {data.campaigns.map((c) => (
                <Item key={c.slug} icon={<span className="font-display text-sm font-bold text-blue">{c.initials}</span>}
                      title={c.name} keys="↵" onSelect={() => run(`campaign:${c.slug}`)}
                      detail={c.warning ?? [c.platform && c.platform.toUpperCase(), c.language.toUpperCase(),
                        `${money(c.rate_per_1k)} / 1 000 vues`].filter(Boolean).join(" · ")} />
              ))}
            </CommandGroup>
          )}
        </CommandList>
        <div className="flex items-center gap-5 border-t border-line px-5 py-3 text-sm text-muted-foreground">
          <span><span className="kbd">↑</span> <span className="kbd">↓</span> naviguer</span>
          <span><span className="kbd">Entrée</span> ouvrir</span>
          <span><span className="kbd">Échap</span> fermer</span>
        </div>
      </Command>
    </CommandDialog>
  );
}

function Item({ icon, title, detail, keys, accent, onSelect }: {
  icon: React.ReactNode; title: string; detail: string; keys: string; accent?: boolean; onSelect: () => void;
}) {
  return (
    <CommandItem onSelect={onSelect} value={`${title} ${detail}`}
                 className="gap-4 rounded-2xl px-3 py-3 data-[selected=true]:bg-yellow-soft">
      <span className={`grid size-11 shrink-0 place-items-center rounded-xl ${accent ? "bg-yellow" : "bg-secondary"} [&_svg]:size-4`}>
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[1.02rem] font-semibold text-ink">{title}</span>
        <span className="block truncate text-sm text-muted-foreground">{detail}</span>
      </span>
      <span className="kbd">{keys}</span>
    </CommandItem>
  );
}
