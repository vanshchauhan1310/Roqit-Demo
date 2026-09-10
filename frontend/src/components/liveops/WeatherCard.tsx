import { useCurrentWeather } from '@/hooks/useCurrentWeather';

const WEATHER_ICON: Record<string, string> = {
  Clear: '☀️',
  Clouds: '☁️',
  Rain: '🌧️',
  Drizzle: '🌦️',
  Thunderstorm: '⛈️',
  Snow: '❄️',
  Mist: '🌫️',
  Fog: '🌫️',
  Haze: '🌫️',
};

const BG_BY_CONDITION: Record<string, string> = {
  Clear: 'from-amber-500/20 to-yellow-500/10',
  Clouds: 'from-slate-500/20 to-gray-500/10',
  Rain: 'from-blue-500/20 to-cyan-500/10',
  Drizzle: 'from-blue-400/20 to-cyan-400/10',
  Thunderstorm: 'from-purple-500/20 to-indigo-500/10',
  Snow: 'from-sky-300/20 to-blue-200/10',
  Mist: 'from-gray-400/20 to-slate-400/10',
  Fog: 'from-gray-400/20 to-slate-400/10',
  Haze: 'from-yellow-400/20 to-amber-300/10',
};

function windLabel(ms: number | null): string {
  if (ms == null) return '—';
  const kmh = ms * 3.6;
  return `${kmh.toFixed(0)} km/h`;
}

function humidityLabel(h: number | null): string {
  if (h == null) return '—';
  return `${h}%`;
}

export function WeatherCard() {
  const { data, isLoading, isError } = useCurrentWeather(60000);

  const condition = data?.condition ?? null;
  const icon = WEATHER_ICON[condition ?? ''] ?? '🌤️';
  const gradient = BG_BY_CONDITION[condition ?? ''] ?? 'from-sky-500/20 to-blue-500/10';

  return (
    <div className={`rounded-xl border border-slate-700/60 bg-gradient-to-br ${gradient} p-3.5 backdrop-blur-sm`}>
      <div className="flex items-center justify-between mb-2.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Live Weather
        </h3>
        <span className="text-[9px] text-slate-500">Hyderabad · 60s</span>
      </div>

      {isLoading && !data && (
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-slate-700/50 animate-pulse" />
          <div className="flex-1 space-y-1.5">
            <div className="h-4 w-20 rounded bg-slate-700/50 animate-pulse" />
            <div className="h-3 w-14 rounded bg-slate-700/50 animate-pulse" />
          </div>
        </div>
      )}

      {isError && !data && (
        <div className="text-xs text-slate-500">
          <span className="text-lg mr-1.5">⚠️</span> Weather unavailable
        </div>
      )}

      {data && (
        <div className="flex items-center gap-3">
          <div className="text-3xl leading-none w-10 text-center">{icon}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-bold text-slate-100 tnum">
                {data.temp_c != null ? `${data.temp_c.toFixed(0)}°` : '—'}
              </span>
              <span className="text-xs text-slate-400">{condition}</span>
            </div>
            {data.description && (
              <div className="text-[10px] text-slate-500 capitalize truncate">{data.description}</div>
            )}
          </div>
        </div>
      )}

      {data && (data.feels_like_c != null || data.humidity != null || data.wind_speed_ms != null) && (
        <div className="grid grid-cols-3 gap-2 mt-2.5 pt-2.5 border-t border-slate-700/40">
          <div>
            <div className="text-[9px] uppercase tracking-wider text-slate-500">Feels like</div>
            <div className="text-xs font-medium text-slate-300 tnum">
              {data.feels_like_c != null ? `${data.feels_like_c.toFixed(0)}°` : '—'}
            </div>
          </div>
          <div>
            <div className="text-[9px] uppercase tracking-wider text-slate-500">Humidity</div>
            <div className="text-xs font-medium text-slate-300 tnum">{humidityLabel(data.humidity)}</div>
          </div>
          <div>
            <div className="text-[9px] uppercase tracking-wider text-slate-500">Wind</div>
            <div className="text-xs font-medium text-slate-300 tnum">{windLabel(data.wind_speed_ms)}</div>
          </div>
        </div>
      )}
    </div>
  );
}