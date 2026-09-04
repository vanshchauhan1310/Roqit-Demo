import { useQuery } from '@tanstack/react-query';
import { fetchCurrentWeather, type WeatherData } from '@/api/weather';

export function useCurrentWeather(pollMs: number = 60000) {
  return useQuery<WeatherData>({
    queryKey: ['weather', 'current'],
    queryFn: fetchCurrentWeather,
    refetchInterval: pollMs,
    staleTime: pollMs / 2,
    retry: 1,
  });
}
