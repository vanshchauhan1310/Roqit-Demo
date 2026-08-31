import { useCallback, useEffect, useRef, useState } from "react";
import { fetchLnsHistory } from "@/api/routes";
import type { LnsRun } from "@/types/lns";

/**
 * Loads recent LNS runs and can wait for a new run to appear after a
 * trigger (the optimizer runs asynchronously on the backend worker).
 */
export function useLnsHistory() {
  const [runs, setRuns] = useState<LnsRun[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const latestIdRef = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchLnsHistory(20);
      setRuns(data);
      if (data.length > 0) latestIdRef.current = data[0].run_id;
    } catch {
      /* backend may be restarting — keep previous data */
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /**
   * Poll until a run newer than `knownRunId` shows up (or timeout).
   * Resolves with the new run, or null on timeout.
   */
  const waitForNewRun = useCallback(
    async (knownRunId: string | null, timeoutMs = 45_000, intervalMs = 2_000): Promise<LnsRun | null> => {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, intervalMs));
        try {
          const data = await fetchLnsHistory(5);
          const newest = data[0];
          if (newest && newest.run_id !== knownRunId) {
            setRuns((prev) => {
              const merged = [...data, ...prev.filter((p) => !data.some((d) => d.run_id === p.run_id))];
              return merged.slice(0, 20);
            });
            latestIdRef.current = newest.run_id;
            return newest;
          }
        } catch {
          /* keep polling */
        }
      }
      return null;
    },
    [],
  );

  return { runs, latestRun: runs[0] ?? null, latestRunId: latestIdRef.current, isLoading, refresh, waitForNewRun };
}