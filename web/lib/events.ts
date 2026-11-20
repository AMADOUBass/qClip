"use client";

// État des tâches en direct : EventSource sur /api/events (SSE). Chaque événement met à jour le cache
// TanStack Query ["jobs"] ; une tâche qui se termine fait rafraîchir les écrans concernés.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { API, type Job, api } from "@/lib/api";

export function useJobEvents() {
  const client = useQueryClient();
  const finished = useRef(new Set<number>());

  useEffect(() => {
    const source = new EventSource(`${API}/api/events`);
    source.addEventListener("jobs", (event) => {
      const { jobs } = JSON.parse((event as MessageEvent).data) as { jobs: Job[] };
      client.setQueryData(["jobs"], jobs);
      for (const job of jobs) {
        if ((job.status === "done" || job.status === "error") && !finished.current.has(job.id)) {
          finished.current.add(job.id);
          // Les données affichées dépendent du résultat : on les recharge.
          client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "jobs" && q.queryKey[0] !== "system" });
        }
      }
    });
    return () => source.close();
  }, [client]);
}

export function useJobs() {
  return useQuery({ queryKey: ["jobs"], queryFn: () => api<Job[]>("/api/jobs"), staleTime: Infinity });
}

export function useCurrentJob() {
  const { data } = useJobs();
  return data?.find((j) => j.status === "running") ?? data?.find((j) => j.status === "queued") ?? null;
}
