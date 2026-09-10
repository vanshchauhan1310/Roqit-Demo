import { useCurrentWeather } from "@/hooks/useCurrentWeather";
import { LiveWeatherCard } from "./LiveWeatherCard";

/**
 * Top-level weather + delay intelligence panel for Live Ops.
 * Shows current conditions; delay badges appear per-route in the plan strip.
 */
export function WeatherDelayPanel() {
  const { data: weather, isLoading } = useCurrentWeather();

  return <LiveWeatherCard weather={weather} loading={isLoading} />;
}