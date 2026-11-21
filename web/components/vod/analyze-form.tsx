"use client";

// « Colle l'URL d'un stream Kick, Twitch ou YouTube » + Analyser (maquette 3, en-tête).
// L'URL est ajoutée aux sources du brief (l'autorisation de la campagne) puis l'analyse part dans la file.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { type Job, post } from "@/lib/api";
import { useCurrentJob } from "@/lib/events";
import { cn } from "@/lib/utils";

const SOURCE_RE = /^https?:\/\/(www\.|m\.)?(kick\.com|twitch\.tv|youtube\.com|youtu\.be)\//i;

/** Lot : plusieurs URL (une par ligne) → une analyse par VOD, mises en file (une à la fois sur cette machine). */
export function BatchForm({ campaign, disabledReason }: { campaign?: string; disabledReason?: string }) {
  const [text, setText] = useState("");
  const router = useRouter();
  const client = useQueryClient();
  const urls = [...new Set(text.split(/\s+/).map((u) => u.trim()).filter(Boolean))];
  const invalid = urls.filter((u) => !SOURCE_RE.test(u));
  const submit = useMutation({
    mutationFn: async () => {
      for (const url of urls) await post(`/api/campaigns/${campaign}/vods`, { url }); // dans l'ordre collé
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["jobs"] });
      toast.success(`${urls.length} analyse${urls.length > 1 ? "s" : ""} en file`, { description: "Elles s'enchaînent seules, une à la fois." });
      setText("");
      router.push("/vod");
    },
    onError: (e) => toast.error(e.message, { duration: 8000 }),
  });
  const blocked = !campaign ? "Choisis d'abord la campagne" : disabledReason;
  return (
    <div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} aria-label="Plusieurs URL, une par ligne"
                placeholder={"https://www.twitch.tv/videos/…\nhttps://kick.com/…/videos/…"}
                className={cn("w-full rounded-2xl border bg-secondary/60 px-4 py-3 font-mono text-sm outline-none focus:border-blue",
                  invalid.length ? "border-pink" : "border-line")} />
      {invalid.length > 0 && <p className="mt-1 text-sm text-pink">Pas une VOD Kick, Twitch ou YouTube : {invalid.join(", ")}</p>}
      <button type="button" title={blocked} disabled={submit.isPending || urls.length < 2 || invalid.length > 0 || !!blocked}
              onClick={() => submit.mutate()}
              className="mt-3 h-12 rounded-2xl bg-ink px-5 font-semibold text-yellow disabled:opacity-40">
        {submit.isPending ? "Envoi…" : `Analyser ${urls.length >= 2 ? `les ${urls.length} VOD` : "le lot"}`}
      </button>
    </div>
  );
}

export function AnalyzeForm({ campaign, disabledReason }: { campaign?: string; disabledReason?: string }) {
  const [url, setUrl] = useState("");
  const router = useRouter();
  const client = useQueryClient();
  const busy = !!useCurrentJob(); // une seule tâche à la fois : la nouvelle attend son tour
  const analyze = useMutation({
    mutationFn: () => post<{ job: Job; source_rule: string }>(`/api/campaigns/${campaign}/vods`, { url: url.trim() }),
    onSuccess: ({ job, source_rule }) => {
      client.invalidateQueries({ queryKey: ["jobs"] });
      toast.success(busy ? "Analyse ajoutée à la file : elle partira après la tâche en cours" : "Analyse lancée", {
        description: source_rule ? `Rappel — règle de source : ${source_rule}` : undefined,
      });
      setUrl("");
      router.push(job.video_id ? `/vod/${job.video_id}` : "/vod");
    },
    onError: (e) => toast.error(e.message, { duration: 8000 }),
  });
  const valid = SOURCE_RE.test(url.trim());
  const blocked = !campaign ? "Choisis d'abord la campagne" : disabledReason;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return toast.error("Colle l'URL d'une VOD Kick, Twitch ou YouTube");
    if (blocked) return toast.error(blocked);
    analyze.mutate();
  };
  return (
    <form onSubmit={submit} className="flex w-[min(40rem,100%)] gap-3">
      <input value={url} onChange={(e) => setUrl(e.target.value)} aria-label="URL de la VOD"
             placeholder="Colle l'URL d'un stream Kick, Twitch ou YouTube"
             className={cn("h-14 min-w-0 flex-1 rounded-2xl border bg-surface px-5 text-[1.05rem] outline-none focus:border-blue",
               url && !valid ? "border-pink" : "border-line")} />
      <button type="submit" disabled={analyze.isPending} title={blocked}
              className={cn("h-14 rounded-2xl bg-yellow px-6 font-semibold disabled:opacity-60", blocked && "opacity-60")}>
        {analyze.isPending ? "Envoi…" : "Analyser"}
      </button>
    </form>
  );
}
