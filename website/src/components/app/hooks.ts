"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Audit, type Run, type Scenario } from "@/lib/api";

/** Fetch a resource; re-poll every `pollMs` while `shouldPoll(data)` is true. */
export function useResource<T>(path: string | null, shouldPoll?: (d: T) => boolean, pollMs = 2500) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!path) return;
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [path]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch; state updates after the request
    reload();
  }, [reload]);

  const poll = data != null && shouldPoll ? shouldPoll(data) : false;
  useEffect(() => {
    if (!poll) return;
    const t = setInterval(reload, pollMs);
    return () => clearInterval(t);
  }, [poll, reload, pollMs]);

  return { data, error, reload };
}

export const isActive = (runs: Run[]) => runs.some((r) => r.status === "queued" || r.status === "running");

export const useRuns = () => useResource<Run[]>("/api/runs", isActive);
export const useScenarios = () => useResource<Scenario[]>("/api/scenarios");
export const useAudits = () => useResource<Audit[]>("/api/audits");
