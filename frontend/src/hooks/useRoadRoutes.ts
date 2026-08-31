import { useEffect, useState } from "react";

type Position = [number, number];

export interface RoadRouteRequest {
  key: string;
  positions: Position[];
}

interface RoadRoutesState {
  geometryByKey: Map<string, Position[]>;
  isLoading: boolean;
}

/** Fetches road-following geometry for every displayed fleet route in parallel.
 * This is presentation-only: optimization still uses the server-side OSRM matrix. */
export function useRoadRoutes(routes: RoadRouteRequest[]): RoadRoutesState {
  const [state, setState] = useState<RoadRoutesState>({ geometryByKey: new Map(), isLoading: false });
  const key = JSON.stringify(routes);

  useEffect(() => {
    const routable = routes.filter((route) => route.positions.length > 1);
    if (!routable.length) {
      setState({ geometryByKey: new Map(), isLoading: false });
      return;
    }

    let cancelled = false;
    setState((previous) => ({ ...previous, isLoading: true }));
    Promise.all(
      routable.map(async (route) => {
        const coordinates = route.positions.map(([lat, lng]) => `${lng},${lat}`).join(";");
        const response = await fetch(
          `https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson`,
        );
        const data = await response.json();
        const points = data?.routes?.[0]?.geometry?.coordinates;
        return [
          route.key,
          Array.isArray(points)
            ? points.map(([lng, lat]: [number, number]) => [lat, lng] as Position)
            : null,
        ] as const;
      }),
    )
      .then((results) => {
        if (cancelled) return;
        const geometryByKey = new Map<string, Position[]>();
        for (const [routeKey, geometry] of results) {
          if (geometry !== null) geometryByKey.set(routeKey, geometry);
        }
        setState({
          geometryByKey,
          isLoading: false,
        });
      })
      .catch(() => {
        if (!cancelled) setState({ geometryByKey: new Map(), isLoading: false });
      });

    return () => { cancelled = true; };
    // The serialized request is the actual dependency; callers often create arrays inline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
