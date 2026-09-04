import { useMemo } from "react";
import { useRoadRoute } from "./useRoadRoute";

export interface RoadRouteRequest {
  key: string;
  positions: [number, number][];
}

/**
 * Aggregate hook: fetches real driving geometry for many routes at once.
 *
 * Each request is delegated to a stable per-request `useRoadRoute` call (the
 * underlying hook caches on the JSON of positions, so identical route shapes
 * don't refetch). The per-request results are batched into a
 * `Map<key, geometry>` plus a single `isLoading` flag.
 */
export function useRoadRoutes(requests: RoadRouteRequest[]) {
  const routes = requests.map((req) => useRoadRoute(req.positions));

  const geometryByKey = useMemo(() => {
    const map = new Map<string, [number, number][]>();
    requests.forEach((req, i) => {
      const geo = routes[i]?.geometry;
      if (geo && geo.length > 1) map.set(req.key, geo);
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requests, ...routes.map((r) => JSON.stringify(r.geometry))]);

  const isLoading = routes.some((r) => r.isLoading);

  return { geometryByKey, isLoading };
}