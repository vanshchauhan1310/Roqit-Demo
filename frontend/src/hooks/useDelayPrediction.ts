import { useMutation, useQueryClient } from "@tanstack/react-query";
import { predictDelayForTrip } from "@/api/predictions";

export function useDelayPrediction(tripId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => predictDelayForTrip(tripId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trip", tripId] });
    },
  });
}
