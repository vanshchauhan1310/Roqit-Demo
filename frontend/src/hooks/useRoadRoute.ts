import { useEffect, useState } from "react";

export interface RoadRoute {
  geometry: [number, number][] | null; // [lat, lng] pairs, road-following
  distanceKm: number | null;
  durationHours: number | null;
  isLoading: boolean;
  isError: boolean;
}

const EMPTY_ROUTE: RoadRoute = {
  geometry: null,
  distanceKm: null,
  durationHours: null,
  isLoading: false,
  isError: false,
};

/**
 * Fetches a real driving route (geometry + distance + duration) between an ordered
 * list of [lat, lng] waypoints via OSRM's free public demo server — no API key needed.
 */
export function useRoadRoute(positions: [number, number][]): RoadRoute {
  const [state, setState] = useState<RoadRoute>(EMPTY_ROUTE);
  const key = JSON.stringify(positions);

  useEffect(() => {
    if (positions.length < 2) {
      setState(EMPTY_ROUTE);
      return;
    }

    let cancelled = false;
    setState((s) => ({ ...s, isLoading: true, isError: false }));

    const coordsParam = positions.map(([lat, lng]) => `${lng},${lat}`).join(";");
    const url = `https://router.project-osrm.org/route/v1/driving/${coordsParam}?overview=full&geometries=geojson`;

    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        const route = data?.routes?.[0];
        const coords = route?.geometry?.coordinates;
        if (route && Array.isArray(coords)) {
          setState({
            geometry: coords.map(([lng, lat]: [number, number]) => [lat, lng] as [number, number]),
            distanceKm: route.distance / 1000,
            durationHours: route.duration / 3600,
            isLoading: false,
            isError: false,
          });
        } else {
          setState({ ...EMPTY_ROUTE, isError: true });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ ...EMPTY_ROUTE, isError: true });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
