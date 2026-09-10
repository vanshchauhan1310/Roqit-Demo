import { apiClient } from './client';

export interface WeatherData {
  condition: string;
  description: string | null;
  temp_c: number | null;
  feels_like_c: number | null;
  humidity: number | null;
  wind_speed_ms: number | null;
  icon: string | null;
  location_name: string | null;
}

export type CurrentWeather = WeatherData;

export async function fetchCurrentWeather(): Promise<WeatherData> {
  const { data } = await apiClient.get<WeatherData>('/weather/current');
  return data;
}