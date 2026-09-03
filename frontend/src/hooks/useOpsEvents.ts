import { useEffect, useRef, useState } from "react";
import type { Trip } from "@/types/trip";
import type { Route } from "@/types/route";
import { colorForRouteId } from "@/utils/routeColors";

export type OpsEventType =
  | "trip_received"
  | "trip_assigned"
  | "route_created"
  | "stops_planned"
  | "lns_triggered";

export interface OpsEvent {
  id: string;
  ts: number;
  type: OpsEventType;
  title: string;
  detail: string;
  color?: string;
  tripId?: string;
  routeId?: string;
}

export interface AssignmentFlight {
  id: string;
  from: [number, number];
  to: [number, number];
  color: string;
  label: string;
  /** Route the trip was assigned to — lets the map color/label the flight
   * to visually connect it with that route's polyline. */
  routeId?: string;
  routeName?: string;
}

const MAX_EVENTS = 60;

let eventSeq = 0;
const mkEvent = (e: Omit<OpsEvent, "id" | "ts">): OpsEvent => ({
  ...e,
  id: `ev-${Date.now()}-${eventSeq++}`,
  ts: Date.now(),
});

/**
 * Turns polling diffs into a live event stream:
 *   trip appears        -> RECEIVED
 *   trip gets route_id  -> ASSIGNED (measured latency + animated flight line)
 *   new route           -> NEW ROUTE CREATED
 *   route gains stops   -> PLAN UPDATED
 */
export function useOpsEvents(
  incoming: Trip[],
  allTrips: Trip[],
  routes: Route[],
): { events: OpsEvent[]; flights: AssignmentFlight[]; latenciesSec: number[]; pushEvent: (e: Omit<OpsEvent, "id" | "ts">) => void } {
  const [events, setEvents] = useState<OpsEvent[]>([]);
  const [flights, setFlights] = useState<AssignmentFlight[]>([]);
  const [latenciesSec, setLatenciesSec] = useState<number[]>([]);

  const firstSeenRef = useRef<Map<string, number>>(new Map());
  const prevTripsRef = useRef<Map<string, { route_id: string | null }>>(new Map());
  const prevRoutesRef = useRef<Map<string, { stops: number }>>(new Map());
  const initializedRef = useRef(false);

  useEffect(() => {
    const nextEvents: OpsEvent[] = [];
    const nextFlights: AssignmentFlight[] = [];
    const now = Date.now();

    // --- Trip lifecycle ---
    const nextTrips = new Map<string, { route_id: string | null; trip: Trip }>();
    for (const t of allTrips) nextTrips.set(t.trip_id, { route_id: t.route_id, trip: t });

    for (const [id, prev] of prevTripsRef.current) {
      const curr = nextTrips.get(id);
      if (!curr) continue;
      if (prev.route_id == null && curr.route_id != null) {
        const route = routes.find((r) => r.route_id === curr.route_id);
        const trip = curr.trip;
        const latencyMs = firstSeenRef.current.get(id);
        const latency = latencyMs ? Math.round((now - latencyMs) / 100) / 10 : null;
        if (latency != null) setLatenciesSec((l) => [...l.slice(-29), latency]);

        nextEvents.push(
          mkEvent({
            type: "trip_assigned",
            title: `ASSIGNED · ${id}`,
            detail:
              `inserted into ${route?.name ?? "route"}` +
              (latency != null ? ` · queue latency ${latency}s` : "") +
              (trip.vehicle_id ? ` · ${trip.vehicle_id}` : ""),
            routeId: curr.route_id ?? undefined,
            tripId: id,
          }),
        );

        // Flight line: the trip's pickup stop -> its delivery stop on the
        // assigned route (the actual legs the vehicle drives for this trip),
        // falling back to the trip's own GPS corners when the stops aren't
        // placed yet. Colored with the ROUTE's color so the flight visually
        // points at the route the trip joined.
        const pickupStop = route?.stops?.find((s) => s.trip_id === id && s.stop_type === "pickup");
        const dropStop = route?.stops?.find((s) => s.trip_id === id && s.stop_type === "delivery");
        let from: [number, number] | null = null;
        let to: [number, number] | null = null;
        if (
          pickupStop?.latitude != null && pickupStop.longitude != null &&
          dropStop?.latitude != null && dropStop.longitude != null
        ) {
          from = [pickupStop.latitude, pickupStop.longitude];
          to = [dropStop.latitude, dropStop.longitude];
        } else if (
          trip.gps_start_lat != null && trip.gps_start_lon != null &&
          trip.gps_end_lat != null && trip.gps_end_lon != null
        ) {
          from = [trip.gps_start_lat, trip.gps_start_lon];
          to = [trip.gps_end_lat, trip.gps_end_lon];
        }
        if (from && to) {
          nextFlights.push({
            id: `fl-${id}-${now}`,
            from,
            to,
            // Route color when the route row is in the poll; neutral teal
            // fallback if it hasn't arrived yet.
            color: route ? colorForRouteId(route.route_id) : "#5eead4",
            label: id,
            routeId: route?.route_id,
            routeName: route ? (route.name ?? route.route_id.slice(0, 8)) : undefined,
          });
        }
      }
    }

    for (const t of allTrips) {
      if (!prevTripsRef.current.has(t.trip_id)) {
        firstSeenRef.current.set(t.trip_id, now);
        if (initializedRef.current) {
          nextEvents.push(
            mkEvent({
              type: "trip_received",
              title: `RECEIVED · ${t.trip_id}`,
              detail: `${t.origin ?? "?"} → ${t.destination ?? "?"}${
                t.load_weight_kg != null ? ` · ${t.load_weight_kg} kg` : ""
              } — queued for assignment`,
              tripId: t.trip_id,
            }),
          );
        }
      }
    }
    prevTripsRef.current = new Map(
      [...nextTrips.entries()].map(([id, v]) => [id, { route_id: v.route_id }]),
    );

    // --- Route lifecycle ---
    const nextRoutes = new Map<string, { stops: number }>();
    for (const r of routes) nextRoutes.set(r.route_id, { stops: r.stops?.length ?? 0 });

    for (const r of routes) {
      const prev = prevRoutesRef.current.get(r.route_id);
      if (!prev) {
        if (initializedRef.current) {
          nextEvents.push(
            mkEvent({
              type: "route_created",
              title: `NEW ROUTE · ${r.name ?? r.route_id.slice(0, 8)}`,
              detail: `vehicle ${r.vehicle_id ?? "—"} opened by the engine — no feasible insertion existed`,
              routeId: r.route_id,
            }),
          );
        }
      } else if ((r.stops?.length ?? 0) > prev.stops) {
        const added = (r.stops?.length ?? 0) - prev.stops;
        nextEvents.push(
          mkEvent({
            type: "stops_planned",
            title: `PLAN UPDATED · ${r.name ?? r.route_id.slice(0, 8)}`,
            detail: `+${added} stop${added > 1 ? "s" : ""} sequenced — now ${r.stops?.length ?? 0} stops`,
            routeId: r.route_id,
          }),
        );
      }
    }
    prevRoutesRef.current = nextRoutes;

    if (nextEvents.length > 0) {
      setEvents((prev) => [...nextEvents.reverse(), ...prev].slice(0, MAX_EVENTS));
    }
    if (nextFlights.length > 0) {
      setFlights((prev) => [...prev, ...nextFlights].slice(-12));
      const ids = new Set(nextFlights.map((f) => f.id));
      // Keep in sync with the .flight-line CSS animation (flight-fade 8s).
      setTimeout(() => setFlights((prev) => prev.filter((f) => !ids.has(f.id))), 8500);
    }

    if (!initializedRef.current) initializedRef.current = true;
  }, [allTrips, routes, incoming]);

  const pushEvent = (e: Omit<OpsEvent, "id" | "ts">) =>
    setEvents((prev) => [mkEvent(e), ...prev].slice(0, MAX_EVENTS));

  return { events, flights, latenciesSec, pushEvent };
}