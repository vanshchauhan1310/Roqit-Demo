import { useMemo } from "react";
import { Trip } from "@/types/trip";
import type { Route } from "@/types/route";
import { useRoutes } from "@/hooks/useRoutes";
import { useTripBreadcrumbs } from "@/hooks/useTripBreadcrumbs";
import { useRoadRoute } from "@/hooks/useRoadRoute";
import { deriveStopProgress } from "@/utils/stopProgress";
import { TripRouteMap } from "./TripRouteMap";
import { MultiStopSequence } from "./MultiStopSequence";
import { RouteStatCards } from "./RouteStatCards";
import { WeatherTrafficRow } from "./WeatherTrafficRow";

interface RouteIntelligenceTabProps {
  trip: Trip;
  route?: Route;
}

export function RouteIntelligenceTab({ trip, route: passedRoute }: RouteIntelligenceTabProps) {
  const { data: routes, isLoading: routesLoading } = useRoutes(passedRoute ? undefined : trip.trip_id);
  const { data: breadcrumbs } = useTripBreadcrumbs(trip.trip_id);

  const route = passedRoute ?? routes?.[0] ?? null;
  const sortedStops = useMemo(
    () => (route ? [...route.stops].sort((a, b) => a.sequence - b.sequence) : []),
    [route],
  );

  const plannedPositions = useMemo(
    () =>
      sortedStops
        .filter((s) => s.latitude != null && s.longitude != null)
        .map((s) => [s.latitude as number, s.longitude as number] as [number, number]),
    [sortedStops],
  );
  const plannedRoute = useRoadRoute(plannedPositions);

  const stopProgress = useMemo(() => (route ? deriveStopProgress(route.stops, trip) : []), [route, trip]);

  const actualTrace: [number, number][] = (breadcrumbs ?? [])
    .filter((b) => b.lat != null && b.lon != null)
    .map((b) => [b.lat as number, b.lon as number]);

  if (routesLoading) {
    return <p className="text-sm text-gray-500">Loading route…</p>;
  }

  if (!route) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6 text-sm text-gray-500">
        No route is linked to this trip yet.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col">
          <h3 className="text-sm font-semibold text-gray-900">Planned vs actual path</h3>
          <p className="text-xs text-gray-500 mt-0.5 mb-3">Dashed = planned route, solid red = actual GPS trace</p>
          <TripRouteMap
            stopProgress={stopProgress}
            plannedGeometry={plannedRoute.geometry}
            actualTrace={actualTrace}
            stopCount={sortedStops.length}
          />
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-900">Multi-stop sequence</h3>
          <p className="text-xs text-gray-500 mt-0.5 mb-1">{sortedStops.length} stops</p>
          <MultiStopSequence stopProgress={stopProgress} />
        </div>
      </div>

      <RouteStatCards
        trip={trip}
        plannedDistanceKm={plannedRoute.distanceKm ?? trip.planned_distance_km}
        plannedDurationHours={plannedRoute.durationHours}
      />

      <WeatherTrafficRow stops={sortedStops} trip={trip} />
    </div>
  );
}
