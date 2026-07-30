import { useNavigate } from "react-router-dom";
import type { Trip } from "@/types/trip";
import { formatDateTime } from "@/utils/format";

const statusStyles: Record<string, string> = {
  "in-transit": "bg-blue-50 text-blue-600",
  delivered: "bg-emerald-50 text-emerald-600",
  delayed: "bg-red-50 text-red-600",
  cancelled: "bg-gray-100 text-gray-500",
};

const statusDot: Record<string, string> = {
  "in-transit": "bg-blue-500",
  delivered: "bg-emerald-500",
  delayed: "bg-red-500",
  cancelled: "bg-gray-400",
};

function driverInitials(name: string | null): string {
  if (!name) return "—";
  const parts = name.trim().split(/\s+/);
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

interface TripsTableProps {
  trips: Trip[];
}

export function TripsTable({ trips }: TripsTableProps) {
  const navigate = useNavigate();

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <table className="min-w-full">
        <thead>
          <tr className="border-b border-gray-100">
            {["Trip ID", "Route", "Driver", "Vehicle", "Status", "Pickup", "ETA", "Delay", "Margin"].map((h) => (
              <th
                key={h}
                className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {trips.map((trip) => {
            const statusKey = trip.status?.toLowerCase() ?? "";
            return (
              <tr
                key={trip.trip_id}
                onClick={() => navigate(`/trips/${trip.trip_id}`)}
                className="cursor-pointer hover:bg-gray-50"
              >
                <td className="px-4 py-3 text-sm font-medium text-gray-900 whitespace-nowrap">{trip.trip_id}</td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    {trip.origin ?? "—"} → {trip.destination ?? "—"}
                    {trip.stop_count > 0 && (
                      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-xs text-gray-500 whitespace-nowrap">
                        ⇄ {trip.stop_count} stops
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-full bg-sky-100 text-sky-700 text-xs font-semibold flex items-center justify-center shrink-0">
                      {driverInitials(trip.driver_name)}
                    </span>
                    {trip.driver_name ?? trip.driver_id ?? "—"}
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">
                  {trip.vehicle_type ?? "—"}
                  {trip.vehicle_id ? ` · ${trip.vehicle_id}` : ""}
                </td>
                <td className="px-4 py-3 text-sm whitespace-nowrap">
                  <span
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                      statusStyles[statusKey] ?? "bg-gray-100 text-gray-500"
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${statusDot[statusKey] ?? "bg-gray-400"}`} />
                    {trip.status ?? "—"}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">
                  {formatDateTime(trip.pickup_time)}
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">
                  {formatDateTime(trip.planned_delivery_time)}
                </td>
                <td className="px-4 py-3 text-sm whitespace-nowrap">
                  {trip.delay_minutes && trip.delay_minutes > 0 ? (
                    <span className="px-2 py-0.5 rounded-full bg-red-50 text-red-600 text-xs font-medium whitespace-nowrap">
                      +{trip.delay_minutes} min
                    </span>
                  ) : (
                    <span className="text-gray-300">—</span>
                  )}
                </td>
                <td
                  className={`px-4 py-3 text-sm font-medium whitespace-nowrap ${
                    trip.profit_margin != null && trip.profit_margin < 0 ? "text-red-600" : "text-emerald-600"
                  }`}
                >
                  {trip.profit_margin != null ? `${trip.profit_margin.toFixed(1)}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
