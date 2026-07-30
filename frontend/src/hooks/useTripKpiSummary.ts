import { useQuery } from "@tanstack/react-query";
import { fetchTripKpiSummary } from "@/api/reports";

export function useTripKpiSummary() {
  return useQuery({
    queryKey: ["trip-kpi-summary"],
    queryFn: fetchTripKpiSummary,
  });
}
