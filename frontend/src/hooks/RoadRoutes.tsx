import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useRoadRoute, type RoadRoute } from "./useRoadRoute";

export interface RoadRouteRequest {
  key: string;
  positions: [number, number][];
}

interface RoadRouteItemProps {
  request: RoadRouteRequest;
  onResult: (key: string, result: RoadRoute) => void;
}

/**
 * Wraps a single `useRoadRoute` call in its own component so that the number
 * of hooks rendered is stable per-item (never called in a loop). Reports its
 * result back up via `onResult`.
 */
function RoadRouteItem({ request, onResult }: RoadRouteItemProps) {
  const result = useRoadRoute(request.positions);
  useEffect(() => {
    onResult(request.key, result);
  }, [result, request.key, onResult]);
  return null;
}

export interface RoadRoutesProps {
  requests: RoadRouteRequest[];
  children: (props: {
    geometryByKey: Map<string, [number, number][]>;
    isLoading: boolean;
  }) => ReactNode;
}

/**
 * Component that fetches real driving geometry for many routes at once.
 *
 * Renders one stable `<RoadRouteItem>` per request (never hooks-in-a-loop),
 * aggregates their results into a `Map<key, geometry>` plus a single
 * `isLoading` flag, and passes those to `children` (render-prop pattern).
 */
export function RoadRoutes({ requests, children }: RoadRoutesProps) {
  const [results, setResults] = useState<Map<string, RoadRoute>>(new Map());

  const onResult = useMemo(
    () => (key: string, result: RoadRoute) => {
      setResults((prev) => {
        const existing = prev.get(key);
        if (
          existing &&
          existing.isLoading === result.isLoading &&
          existing.isError === result.isError &&
          JSON.stringify(existing.geometry) === JSON.stringify(result.geometry) &&
          existing.distanceKm === result.distanceKm &&
          existing.durationHours === result.durationHours
        ) {
          return prev; // no change — avoid re-render storm
        }
        const next = new Map(prev);
        next.set(key, result);
        return next;
      });
    },
    [],
  );

  const geometryByKey = useMemo(() => {
    const map = new Map<string, [number, number][]>();
    results.forEach((result, key) => {
      if (result.geometry && result.geometry.length > 1) map.set(key, result.geometry);
    });
    return map;
  }, [results]);

  const isLoading = useMemo(
    () => Array.from(results.values()).some((r) => r.isLoading),
    [results],
  );

  return (
    <>
      {requests.map((req) => (
        <RoadRouteItem key={req.key} request={req} onResult={onResult} />
      ))}
      {children({ geometryByKey, isLoading })}
    </>
  );
}