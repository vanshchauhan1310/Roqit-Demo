import type { RouteStop } from "@/types/route";
import type { Trip } from "@/types/trip";

export type StopProgressStatus = "completed" | "delayed" | "pending";

export interface StopProgress {
  stop: RouteStop;
  arrivedAt: Date | null;
  status: StopProgressStatus;
}

const RESOLVED_STATUSES = new Set(["delivered", "delayed", "cancelled"]);

/**
 * There's no real per-stop arrival telemetry (route_stops has no arrived_at
 * column), so "arrivedAt" is the backend's rule-based ETA (real OSRM leg
 * duration x the same weather multiplier eta_service uses), persisted on
 * stop.eta by route_service.compute_weather_eta — the SAME timeline the map
 * and stat cards are built from, not an independently-fabricated one. The
 * first stop has no computed eta (compute_weather_eta only walks legs from
 * stop 2 onward), so it falls back to the trip's own pickup_time. Reached/
 * pending is derived from the trip's real status; "delayed" is a real
 * comparison against the stop's own window_end, or the trip's own Delayed
 * status attributed to the last reached stop.
 */
export function deriveStopProgress(stops: RouteStop[], trip: Trip): StopProgress[] {
  const sorted = [...stops].sort((a, b) => a.sequence - b.sequence);
  const n = sorted.length;
  const statusLower = (trip.status ?? "").toLowerCase();

  let reachedCount: number;
  if (RESOLVED_STATUSES.has(statusLower)) {
    reachedCount = n;
  } else if (statusLower === "in-transit") {
    reachedCount = Math.max(n - 1, 0);
  } else {
    reachedCount = 0;
  }

  const lastReachedIndex = reachedCount - 1;

  return sorted.map((stop, index) => {
    if (index >= reachedCount) {
      return { stop, arrivedAt: null, status: "pending" as const };
    }

    const arrivedAt = stop.eta
      ? new Date(stop.eta)
      : index === 0 && trip.pickup_time
        ? new Date(trip.pickup_time)
        : null;

    const windowEnd = stop.window_end ? new Date(stop.window_end) : null;
    const pastWindow = Boolean(arrivedAt && windowEnd && arrivedAt.getTime() > windowEnd.getTime());
    const tripMarkedDelayed = statusLower === "delayed" && index === lastReachedIndex;

    const status: StopProgressStatus = pastWindow || tripMarkedDelayed ? "delayed" : "completed";
    return { stop, arrivedAt, status };
  });
}

export const stopProgressBadgeStyle: Record<StopProgressStatus, string> = {
  completed: "bg-emerald-50 text-emerald-700",
  delayed: "bg-red-50 text-red-600",
  pending: "bg-gray-100 text-gray-500",
};

export const stopProgressLabel: Record<StopProgressStatus, string> = {
  completed: "Completed",
  delayed: "Delayed",
  pending: "Pending",
};

export const stopProgressMarkerColor: Record<StopProgressStatus, string> = {
  completed: "#10b981",
  delayed: "#ef4444",
  pending: "#9ca3af",
};
