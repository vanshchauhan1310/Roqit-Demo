import { useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useRouteDetail } from "@/hooks/useRouteDetail";
import { useTripDetail } from "@/hooks/useTripDetail";
import { RouteDetailTabs } from "@/components/trip/RouteDetailTabs";

function shortId(routeId: string): string {
  return routeId.length > 8 ? `…${routeId.slice(-8)}` : routeId;
}

export function RouteDetailPage() {
  const { routeId } = useParams<{ routeId: string }>();
  const { data: route, isLoading, isError } = useRouteDetail(routeId);

  const firstTripId = useMemo(() => {
    if (!route) return undefined;
    return route.stops.find((s) => s.trip_id)?.trip_id ?? undefined;
  }, [route]);

  const { data: trip } = useTripDetail(firstTripId);
  const hasLinkedTrips = Boolean(route && firstTripId);

  return (
    <div>
      <Link to="/trips" className="text-sm text-blue-600 hover:underline">
        ← Back to Trips
      </Link>

      {isLoading && <p className="text-sm text-gray-500 mt-4">Loading route…</p>}
      {isError && <p className="text-sm text-red-600 mt-4">Failed to load route.</p>}

      {route && (
        <div className="mt-4">
          <h1 className="text-xl font-semibold text-gray-900 mb-1">
            {route.name ?? `Route ${shortId(route.route_id)}`}
          </h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-500 mb-6">
            <span className="font-mono">{shortId(route.route_id)}</span>
            <span className="text-gray-300">·</span>
            <span>{route.stops.length} stops</span>
            <span className="text-gray-300">·</span>
            <span>Driver {route.driver_id ?? "—"}</span>
            <span className="text-gray-300">·</span>
            <span>Vehicle {route.vehicle_id ?? "—"}</span>
          </div>

          {!hasLinkedTrips && (
            <p className="text-sm text-gray-500">
              This route has no trips linked to its stops, so trip-scoped intelligence (route, vehicle, driver,
              real-time, reporting) isn't available for it.
            </p>
          )}
          {hasLinkedTrips && (trip ? (
            <RouteDetailTabs route={route} trip={trip} />
          ) : (
            <p className="text-sm text-gray-500">Loading route intelligence…</p>
          ))}
        </div>
      )}
    </div>
  );
}