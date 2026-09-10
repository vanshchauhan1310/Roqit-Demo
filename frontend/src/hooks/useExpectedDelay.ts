import { useQuery } from '@tanstack/react-query';
import { predictExpectedDelayForTrip } from '@/api/predictions';
import type { ExpectedDelay } from '@/types/delayPrediction';

export function useExpectedDelay(tripId: string) {
  return useQuery<ExpectedDelay, Error>({
    queryKey: ['expected-delay', tripId],
    queryFn: () => predictExpectedDelayForTrip(tripId),
    enabled: !!tripId,
    staleTime: 2 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: 1,
  });
}