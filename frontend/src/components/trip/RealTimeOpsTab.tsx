import { useMemo } from "react";
import { Trip } from "@/types/trip";
import { useTripBreadcrumbs } from "@/hooks/useTripBreadcrumbs";
import { useRealtimeLive } from "@/hooks/useRealtimeLive";
import { GpsBreadcrumb } from "@/types/gpsBreadcrumb";
import { TripRouteMap } from "./TripRouteMap";
import { DelayRiskCard } from "./DelayRiskCard";

interface RealTimeOpsTabProps {
  trip: Trip;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function formatNumber(value: number | null | undefined, suffix = ""): string {
  return value != null && Number.isFinite(value) ? `${value.toLocaleString()}${suffix}` : "—";
}

function formatSpeed(value: number | null | undefined): string {
  return value != null && Number.isFinite(value) ? `${value.toFixed(1)} km/h` : "—";
}

function headingLabel(deg: number | null | undefined): string {
  if (deg == null) return "—";
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return dirs[Math.round(((deg % 360) + 360) % 360 / 45) % 8] ?? "—";
}

export function RealTimeOpsTab({ trip }: RealTimeOpsTabProps) {
  const { data: breadcrumbs, isLoading: breadcrumbsLoading } = useTripBreadcrumbs(trip.trip_id);
  const { data: live, isLoading: liveLoading, refetch } = useRealtimeLive(trip.trip_id);

  const actualTrace: [number, number][] = useMemo(
    () =>
      (breadcrumbs ?? [])
        .filter((b) => b.lat != null && b.lon != null)
        .map((b) => [b.lat as number, b.lon as number]),
    [breadcrumbs],
  );

  const latestBreadcrumb: GpsBreadcrumb | undefined = breadcrumbs?.[breadcrumbs.length - 1];

  if (liveLoading || breadcrumbsLoading) {
    return <p className="text-sm text-gray-500">Loading live telemetry…</p>;
  }

  return (
    <div className="space-y-6">
      <LiveStatusRow live={live} latestBreadcrumb={latestBreadcrumb} onRefresh={refetch} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col">
          <h3 className="text-sm font-semibold text-gray-900">Live GPS trace</h3>
          <p className="text-xs text-gray-500 mt-0.5 mb-3">Solid red = actual GPS breadcrumbs recorded for this trip</p>
          <TripRouteMap stopProgress={[]} plannedGeometry={null} actualTrace={actualTrace} stopCount={0} />
        </div>

        <BreadcrumbFeed breadcrumbs={breadcrumbs ?? []} />
      </div>

      <DelayRiskCard trip={trip} />
    </div>
  );
}

const STATUS_BADGE: Record<string, string> = {
  "in-transit": "bg-sky-50 text-sky-700",
  delivered: "bg-emerald-50 text-emerald-700",
  delayed: "bg-amber-50 text-amber-700",
  scheduled: "bg-gray-100 text-gray-500",
  planned: "bg-gray-100 text-gray-500",
  cancelled: "bg-red-50 text-red-600",
};

function LiveStatusRow({
  live,
  latestBreadcrumb,
  onRefresh,
}: {
  live: ReturnType<typeof useRealtimeLive>["data"];
  latestBreadcrumb: GpsBreadcrumb | undefined;
  onRefresh: () => void;
}) {
  const speed = live?.current_speed_kmph ?? latestBreadcrumb?.speed_kmph ?? null;
  const heading = live?.latest_heading_deg ?? latestBreadcrumb?.heading_deg ?? null;
  const timestamp = live?.latest_timestamp ?? latestBreadcrumb?.timestamp ?? null;
  const vehicleStatus = live?.vehicle_status;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-gray-900">Vehicle {live?.vehicle_id ?? "—"}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            Trip status:{" "}
            <span className={`px-1.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[live?.status?.toLowerCase() ?? ""] ?? "bg-gray-100 text-gray-500"}`}>
              {live?.status ?? "—"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {vehicleStatus && (
            <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
              {vehicleStatus}
            </span>
          )}
          <button
            onClick={onRefresh}
            className="px-3 py-1.5 text-xs font-medium text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50"
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4 pt-4 border-t border-gray-100">
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">Current speed</div>
          <div className="text-lg font-semibold text-gray-900 mt-0.5">{formatSpeed(speed)}</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">Heading</div>
          <div className="text-lg font-semibold text-gray-900 mt-0.5">
            {headingLabel(heading)}
            {heading != null && <span className="text-xs text-gray-400 ml-1">({Math.round(((heading % 360) + 360) % 360)}°)</span>}
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">Breadcrumbs</div>
          <div className="text-lg font-semibold text-gray-900 mt-0.5">{formatNumber(live?.breadcrumb_count)}</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">Last GPS fix</div>
          <div className="text-sm font-semibold text-gray-900 mt-1">{formatDate(timestamp)}</div>
        </div>
      </div>

      {live?.alert_flag && (
        <div className="mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs font-medium text-red-600">
          Fleet alert: {live.alert_flag}
        </div>
      )}
    </div>
  );
}

function BreadcrumbFeed({ breadcrumbs }: { breadcrumbs: GpsBreadcrumb[] }) {
  if (breadcrumbs.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <h3 className="text-sm font-semibold text-gray-900">Breadcrumb feed</h3>
        <p className="text-xs text-gray-400 mt-2">No GPS breadcrumbs recorded for this trip yet.</p>
      </div>
    );
  }

  const recent = [...breadcrumbs].reverse().slice(0, 12);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Breadcrumb feed</h3>
      <p className="text-xs text-gray-500 mt-0.5 mb-2">Latest {recent.length} of {breadcrumbs.length} GPS fixes</p>
      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-100">
              <th className="py-1.5 pr-2 font-semibold">Time</th>
              <th className="py-1.5 px-2 font-semibold">Speed</th>
              <th className="py-1.5 px-2 font-semibold">Heading</th>
              <th className="py-1.5 pl-2 font-semibold">Position</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((b) => (
              <tr key={b.id} className="border-b border-gray-50 last:border-b-0">
                <td className="py-2 pr-2 text-gray-600 whitespace-nowrap">{formatDate(b.timestamp)}</td>
                <td className="py-2 px-2 text-gray-700 whitespace-nowrap">{formatSpeed(b.speed_kmph)}</td>
                <td className="py-2 px-2 text-gray-700 whitespace-nowrap">{headingLabel(b.heading_deg)}</td>
                <td className="py-2 pl-2 text-gray-500 truncate max-w-40">
                  {b.lat != null && b.lon != null ? `${b.lat.toFixed(4)}, ${b.lon.toFixed(4)}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}