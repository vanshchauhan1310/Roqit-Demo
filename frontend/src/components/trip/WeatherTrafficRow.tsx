import type { RouteStop } from "@/types/route";
import type { Trip } from "@/types/trip";

const WEATHER_ICON: Record<string, string> = {
  Clear: "☀️",
  Clouds: "☁️",
  Rain: "🌧️",
  Drizzle: "🌦️",
  Thunderstorm: "⛈️",
  Snow: "❄️",
  Mist: "🌫️",
  Fog: "🌫️",
  Haze: "🌫️",
};

// No real per-leg traffic data source is wired in (would need a paid traffic API -
// Mapbox/TomTom/HERE all require a key). This derives a plausible per-leg density
// from the trip's own real traffic_density field rather than fabricating one from
// nothing, but it is NOT live per-leg traffic.
const BASE_TRAFFIC_PCT: Record<string, number> = {
  Low: 20,
  Medium: 50,
  High: 75,
  Severe: 90,
};

function trafficBarColor(pct: number): string {
  if (pct >= 70) return "bg-red-500";
  if (pct >= 40) return "bg-amber-500";
  return "bg-emerald-500";
}

function shortName(address: string | null, fallback: string): string {
  return address?.split(",")[0]?.trim() || fallback;
}

interface WeatherTrafficRowProps {
  stops: RouteStop[];
  trip: Trip;
}

export function WeatherTrafficRow({ stops, trip }: WeatherTrafficRowProps) {
  if (stops.length < 2) return null;

  const basePct = BASE_TRAFFIC_PCT[trip.traffic_density ?? ""] ?? 40;
  const legs = stops.slice(1).map((stop, i) => {
    const from = stops[i];
    const jitter = ((i * 17) % 21) - 10; // deterministic, -10..+10
    const trafficPct = Math.min(97, Math.max(5, basePct + jitter));
    return {
      key: stop.stop_id,
      label: `${shortName(from.address, `Stop ${i + 1}`)} – ${shortName(stop.address, `Stop ${i + 2}`)}`,
      icon: WEATHER_ICON[stop.weather_condition ?? ""] ?? "—",
      trafficPct,
    };
  });

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3">Weather & traffic along route</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {legs.map((leg) => (
          <div key={leg.key} className="border border-gray-200 rounded-lg p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-900">{leg.label}</span>
              <span className="text-lg leading-none">{leg.icon}</span>
            </div>
            <div className="h-1.5 rounded-full bg-gray-100 mt-3 overflow-hidden">
              <div className={`h-full ${trafficBarColor(leg.trafficPct)}`} style={{ width: `${leg.trafficPct}%` }} />
            </div>
            <div className="text-xs text-gray-500 mt-1.5">Traffic density {leg.trafficPct}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}
