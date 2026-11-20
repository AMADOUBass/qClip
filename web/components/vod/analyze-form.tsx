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
