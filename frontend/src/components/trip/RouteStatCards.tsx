import { isAxiosError } from "axios";
import { Trip } from "@/types/trip";
import { useExpectedDelay } from "@/hooks/useExpectedDelay";
import { useAutoDelayRisk } from "@/hooks/useAutoDelayRisk";
import { riskBadge } from "@/utils/riskBadge";

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function errorDetail(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Prediction unavailable";
}

interface RouteStatCardsProps {
  trip: Trip;
  plannedDistanceKm: number | null;
  plannedDurationHours: number | null;
  hasActualTelemetry: boolean;
}

export function RouteStatCards({ trip, plannedDistanceKm, plannedDurationHours, hasActualTelemetry }: RouteStatCardsProps) {
  const expectedDelay = useExpectedDelay(trip.trip_id);
  const delayRisk = useAutoDelayRisk(trip.trip_id);

  // Planned ETA is computed here from real distance/road-network duration
  // (the same OSRM-based figure shown on the map), not the stored
  // planned_delivery_time, per the "based on distance" requirement.
  const pickupTime = trip.pickup_time ? new Date(trip.pickup_time) : null;
  const plannedEta =
    pickupTime && plannedDurationHours != null
      ? new Date(pickupTime.getTime() + plannedDurationHours * 3600 * 1000)
      : null;

  const predictedEta =
    plannedEta && expectedDelay.data
      ? new Date(plannedEta.getTime() + expectedDelay.data.predicted_delay_minutes * 60 * 1000)
      : null;

  const badge = delayRisk.data ? riskBadge(delayRisk.data.delay_probability) : null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
      <StatCard label="Planned Distance" value={plannedDistanceKm != null ? `${Math.round(plannedDistanceKm)} km` : "—"} />

      <StatCard
        label="Actual Distance"
        value={hasActualTelemetry && trip.actual_distance_km != null ? `${Math.round(trip.actual_distance_km)} km` : "—"}
        sub={hasActualTelemetry ? "GPS telemetry" : "Awaiting GPS telemetry"}
      />

      <StatCard label="Planned ETA" value={plannedEta ? formatTime(plannedEta) : "—"} sub={pickupTime ? pickupTime.toLocaleDateString() : undefined} />

      <StatCard
        label="Predicted ETA"
        value={predictedEta ? formatTime(predictedEta) : expectedDelay.isLoading ? "…" : "—"}
        valueClassName="text-red-600"
        sub={expectedDelay.isError ? errorDetail(expectedDelay.error) : "AI-flagged prediction"}
      />

      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-2">Delay Risk Score</div>
        {badge ? (
          <div className="flex items-center gap-2">
            <span className={`px-2.5 py-1 rounded-full text-sm font-medium ${badge.className}`}>{badge.label}</span>
            <span className="text-xs text-gray-500">
              {(delayRisk.data!.delay_probability * 100).toFixed(0)}% confidence
            </span>
          </div>
        ) : (
          <span className="text-sm text-gray-400">
            {delayRisk.isLoading ? "…" : delayRisk.isError ? errorDetail(delayRisk.error) : "—"}
          </span>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  valueClassName = "text-gray-900",
}: {
  label: string;
  value: string;
  sub?: string;
  valueClassName?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-2">{label}</div>
      <div className={`text-2xl font-semibold ${valueClassName}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}
