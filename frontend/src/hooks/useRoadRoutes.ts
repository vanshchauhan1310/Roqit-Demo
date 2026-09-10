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
  // React hooks must be called a constant number of times across renders — you
  // cannot map over an array and call a hook inside the loop unless the count
  // is stable. Routes are added/closed live (the engine opens new routes), so
  // `requests.length` changes every poll -> calling useRoadRoute in the loop
  // threw "Rendered more hooks than during the previous render" and blanked
  // the Live Ops page. We therefore call useRoadRoute a FIXED number of times
  // (MAX_SLOTS), filling empty slots with nothing and ignoring extras.
  const MAX_SLOTS = 6;
  const slots: RoadRouteRequest[] = [];
  for (let i = 0; i < MAX_SLOTS; i++) {
    slots.push(requests[i] ?? { key: `__empty-${i}__`, positions: [] });
  }
  const routes = slots.map((req) => useRoadRoute(req.positions));

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