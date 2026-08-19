import { useNavigate } from "react-router-dom";
import type { Route } from "@/types/route";
import { formatDateTime } from "@/utils/format";

const statusStyles: Record<string, string> = {
  planned: "bg-gray-100 text-gray-600",
  active: "bg-blue-50 text-blue-600",
  "in-transit": "bg-blue-50 text-blue-600",
  completed: "bg-emerald-50 text-emerald-600",
  delivered: "bg-emerald-50 text-emerald-600",
  cancelled: "bg-red-50 text-red-600",
};

const statusDot: Record<string, string> = {
  planned: "bg-gray-400",
  active: "bg-blue-500",
  "in-transit": "bg-blue-500",
  completed: "bg-emerald-500",
  delivered: "bg-emerald-500",
  cancelled: "bg-red-500",
};

function shortId(routeId: string): string {
  return routeId.length > 8 ? `…${routeId.slice(-8)}` : routeId;
}

interface RoutesTableProps {
  routes: Route[];
}

export function RoutesTable({ routes }: RoutesTableProps) {
  const navigate = useNavigate();

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <table className="min-w-full">
        <thead>
          <tr className="border-b border-gray-100">
            {["Route", "Status", "Trips", "Stops", "Driver", "Vehicle", "Pickup", "Created"].map((h) => (
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
          {routes.map((route) => {
            const statusKey = route.status?.toLowerCase() ?? "";
            const tripIds = Array.from(new Set(route.stops.map((s) => s.trip_id).filter((id): id is string => Boolean(id))));
            return (
              <tr
                key={route.route_id}
                onClick={() => navigate(`/routes/${route.route_id}`)}
                className="cursor-pointer hover:bg-gray-50"
              >
                <td className="px-4 py-3 text-sm text-gray-900 whitespace-nowrap">
                  <div className="font-medium">{route.name ?? shortId(route.route_id)}</div>
                  <div className="text-xs text-gray-400 font-mono">{shortId(route.route_id)}</div>
                </td>
                <td className="px-4 py-3 text-sm whitespace-nowrap">
                  <span
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                      statusStyles[statusKey] ?? "bg-gray-100 text-gray-500"
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${statusDot[statusKey] ?? "bg-gray-400"}`} />
                    {route.status ?? "—"}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">{tripIds.length} trips</td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-xs text-gray-500">
                    ⇄ {route.stops.length} stops
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">{route.driver_id ?? "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{route.vehicle_id ?? "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{formatDateTime(route.pickup_time)}</td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{formatDateTime(route.created_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
