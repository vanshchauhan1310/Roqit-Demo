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
 * first stop's eta is the route pickup_time itself, and every later stop's
 * eta accumulates leg durations from there.
 *
 * A stop only becomes "completed" once the current time has actually passed
 * its arrivedAt — not just because the trip's overall status is In-Transit.
 * That's what previously made every stop but the last flip to Completed the
 * moment a trip went In-Transit, regardless of whether its eta had passed.
 * The backend also lazily flips stop.status pending -> done once its eta
 * passes, and we honor that as authoritative. Once the trip itself resolves
 * (Delivered/Delayed/Cancelled), every stop is treated as reached since the
 * trip is over.
 */
export function deriveStopProgress(stops: RouteStop[], trip: Trip): StopProgress[] {
  const sorted = [...stops].sort((a, b) => a.sequence - b.sequence);
  const statusLower = (trip.status ?? "").toLowerCase();
  const tripResolved = RESOLVED_STATUSES.has(statusLower);
  const now = Date.now();

  const lastIndex = sorted.length - 1;

  return sorted.map((stop, index) => {
    const arrivedAt = stop.eta
      ? new Date(stop.eta)
      : index === 0 && trip.pickup_time
        ? new Date(trip.pickup_time)
        : null;

    const reached =
      tripResolved ||
      stop.status === "done" ||
      (arrivedAt != null && arrivedAt.getTime() <= now);
    if (!reached) {
      return { stop, arrivedAt: null, status: "pending" as const };
    }

    const windowEnd = stop.window_end ? new Date(stop.window_end) : null;
    const pastWindow = Boolean(arrivedAt && windowEnd && arrivedAt.getTime() > windowEnd.getTime());
    const tripMarkedDelayed = statusLower === "delayed" && index === lastIndex;

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
