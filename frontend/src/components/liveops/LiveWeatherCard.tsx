import type { CurrentWeather } from "@/api/weather";

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

function weatherIcon(condition: string): string {
  return WEATHER_ICON[condition] ?? "🌤️";
}

function weatherSeverity(condition: string): "good" | "warn" | "bad" {
  switch (condition) {
    case "Clear":
    case "Clouds":
      return "good";
    case "Drizzle":
    case "Mist":
    case "Haze":
      return "warn";
    case "Rain":
    case "Fog":
    case "Snow":
    case "Thunderstorm":
      return "bad";
    default:
      return "good";
  }
}

interface LiveWeatherCardProps {
  weather: CurrentWeather | undefined;
  loading: boolean;
}

export function LiveWeatherCard({ weather, loading }: LiveWeatherCardProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-3 animate-pulse">
        <div className="h-4 w-24 bg-slate-800 rounded mb-2" />
        <div className="h-8 w-32 bg-slate-800 rounded" />
      </div>
    );
  }

  if (!weather) {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-400">
            📍 Hyderabad
          </span>
          <span className="text-[10px] text-amber-400/80">demo mode</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-3xl leading-none">🌤️</span>
          <div>
            <div className="text-xl font-semibold text-slate-100 leading-tight">24°C</div>
            <div className="text-xs text-slate-400">Partly cloudy · set OPENWEATHER_API_KEY for live</div>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 mt-3 pt-2 border-t border-slate-800">
          <div>
            <div className="text-[9px] uppercase text-slate-500">Feels like</div>
            <div className="text-xs text-slate-300">26°</div>
          </div>
          <div>
            <div className="text-[9px] uppercase text-slate-500">Humidity</div>
            <div className="text-xs text-slate-300">68%</div>
          </div>
          <div>
            <div className="text-[9px] uppercase text-slate-500">Wind</div>
            <div className="text-xs text-slate-300">3.2 m/s</div>
          </div>
        </div>
      </div>
    );
  }

  const severity = weatherSeverity(weather.condition);
  const accent =
    severity === "good"
      ? "border-emerald-600/40"
      : severity === "warn"
        ? "border-amber-600/40"
        : "border-red-600/40";

  return (
    <div className={`rounded-xl border ${accent} bg-slate-900/70 p-3 transition-colors`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider text-slate-400">
          📍 {weather.location_name ?? "Hyderabad"}
        </span>
        <span className="text-[10px] text-slate-500">live</span>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-3xl leading-none">{weatherIcon(weather.condition)}</span>
        <div>
          <div className="text-xl font-semibold text-slate-100 leading-tight">
            {weather.temp_c != null ? `${Math.round(weather.temp_c)}°C` : "—"}
          </div>
          <div className="text-xs text-slate-400 capitalize">
            {weather.description ?? weather.condition}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-3 pt-2 border-t border-slate-800">
        <div>
          <div className="text-[9px] uppercase text-slate-500">Feels like</div>
          <div className="text-xs text-slate-300">
            {weather.feels_like_c != null ? `${Math.round(weather.feels_like_c)}°` : "—"}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-slate-500">Humidity</div>
          <div className="text-xs text-slate-300">
            {weather.humidity != null ? `${weather.humidity}%` : "—"}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-slate-500">Wind</div>
          <div className="text-xs text-slate-300">
            {weather.wind_speed_ms != null ? `${weather.wind_speed_ms.toFixed(1)} m/s` : "—"}
          </div>
        </div>
      </div>
    </div>
  );
}