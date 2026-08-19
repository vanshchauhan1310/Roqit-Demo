import { useQuery } from "@tanstack/react-query";
import { fetchTripKpiDetail } from "@/api/reports";

export function useTripKpiDetail() {
  return useQuery({
    queryKey: ["trip-kpi-detail"],
    queryFn: fetchTripKpiDetail,
  });
}
