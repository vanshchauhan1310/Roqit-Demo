import { useMutation } from "@tanstack/react-query";
import { predictMlEtaForTrip } from "@/api/predictions";

export function useMlEtaPrediction(tripId: string) {
  return useMutation({
    mutationFn: () => predictMlEtaForTrip(tripId),
  });
}
