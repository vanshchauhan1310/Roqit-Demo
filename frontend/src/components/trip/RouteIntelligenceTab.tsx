import { Card } from "@/components/common/Card";
import { Trip } from "@/types/trip";
import { RouteStop } from "@/types/route";
import { useRouteForTrip } from "@/hooks/useRouteForTrip";
import { useRoadRoute } from "@/hooks/useRoadRoute";
import { RouteMapPreview } from "./RouteMapPreview";
import { MlEtaCard } from "./MlEtaCard";

interface RouteIntelligenceTabProps {
  trip: Trip;
}

function locatedStops(stops: RouteStop[]) {
  return stops.filter((s) => s.latitude != null && s.longitude != null);
}

export function RouteIntelligenceTab({ trip }: RouteIntelligenceTabProps) {
  const { data: route, isLoading, isError } = useRouteForTrip(trip.trip_id);

  const stops = route ? locatedStops(route.stops) : [];
  const positions: [number, number][] = stops.map((s) => [s.latitude as number, s.longitude as number]);
  const roadRoute = useRoadRoute(positions);

  if (isLoading) {
    return (
      <Card title="Route Intelligence">
        <p className="text-sm text-gray-500">Loading route…</p>
      </Card>
    );
  }

  if (isError || !route) {
    return (
      <Card title="Route Intelligence">
        <p className="text-sm text-gray-500">
          No route has been created for trip {trip.trip_id.slice(0, 8)} yet.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card title="Route Map">
        <RouteMapPreview
          stops={stops.map((s) => ({
            key: s.stop_id,
            lat: s.latitude as number,
            lng: s.longitude as number,
            label: s.address ?? `Stop ${s.sequence}`,
            sequence: s.sequence,
          }))}
          routeGeometry={roadRoute.geometry}
          isRouteLoading={roadRoute.isLoading}
          isRouteError={roadRoute.isError}
        />
      </Card>

      <Card title="Stop Sequence">
        <div className="divide-y divide-gray-100">
          {route.stops.map((stop) => (
            <div key={stop.stop_id} className="py-3 flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-sky-100 text-sky-700 text-xs font-semibold flex items-center justify-center">
                    {stop.sequence}
                  </span>
                  <span className="text-sm font-medium text-gray-900">{stop.address ?? "Unnamed stop"}</span>
                  <span className="text-xs text-gray-400 uppercase">{stop.stop_type}</span>
                </div>
                {stop.eta && (
                  <p className="text-xs text-gray-500 mt-1 ml-8">ETA: {new Date(stop.eta).toLocaleString()}</p>
                )}
              </div>
              {stop.weather_condition && (
                <div className="text-right shrink-0">
                  <p className="text-sm text-gray-700">{stop.weather_condition}</p>
                  {stop.temperature_c != null && (
                    <p className="text-xs text-gray-400">{stop.temperature_c.toFixed(0)}°C</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>

      {route.weather_eta && (
        <Card title="Weather-Adjusted ETA">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Stat label="Distance" value={`${route.weather_eta.distance_km.toFixed(1)} km`} />
            <Stat label="Base duration" value={`${route.weather_eta.base_duration_minutes.toFixed(0)} min`} />
            <Stat
              label="Weather"
              value={`${route.weather_eta.weather_condition} (${route.weather_eta.weather_delay_multiplier}x)`}
            />
            <Stat label="Adjusted ETA" value={`${route.weather_eta.adjusted_duration_minutes.toFixed(0)} min`} />
          </div>
        </Card>
      )}

      <MlEtaCard trip={trip} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-1">{label}</div>
      <div className="text-sm font-medium text-gray-900">{value}</div>
    </div>
  );
}
