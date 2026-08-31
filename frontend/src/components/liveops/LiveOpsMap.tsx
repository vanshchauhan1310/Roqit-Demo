import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, Marker, Polyline, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import type { Trip } from "@/types/trip";
import type { Route } from "@/types/route";
import { HYDERABAD_CENTER, HYDERABAD_BOUNDS } from "@/utils/serviceArea";
import { colorForRouteId } from "@/utils/routeColors";
import type { AssignmentFlight } from "@/hooks/useOpsEvents";

/** Cache icon instances — react-leaflet replaces marker DOM whenever the
 * `icon` prop identity changes, so recreating icons inline in JSX made every
 * marker visually "restart" (perceived as pulsating) on each poll cycle. */
const iconCache = new Map<string, L.DivIcon>();

function cachedIcon(key: string, build: () => L.DivIcon): L.DivIcon {
  let icon = iconCache.get(key);
  if (!icon) {
    icon = build();
    iconCache.set(key, icon);
  }
  return icon;
}

/** Amber pulsing dot for trips waiting for assignment (the ONLY animated marker). */
function incomingIcon() {
  return cachedIcon("incoming", () =>
    L.divIcon({
      className: "",
      html: `<div style="position:relative;width:18px;height:18px">
        <span style="position:absolute;inset:0;background:#f59e0b;border-radius:9999px;opacity:0.45;animation:liveops-pulse 2s ease-out infinite"></span>
        <span style="position:absolute;inset:4px;background:#f59e0b;border:2px solid #fff;border-radius:9999px;box-shadow:0 1px 3px rgba(0,0,0,0.35)"></span>
      </div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    }),
  );
}

function FitBounds({ incoming, selectedRoute }: { incoming: Trip[]; selectedRoute: Route | null }) {
  const map = useMap();
  const positions = useMemo<[number, number][]>(() => {
    const pts: [number, number][] = incoming
      .filter((t) => t.gps_start_lat != null && t.gps_start_lon != null)
      .map((t) => [t.gps_start_lat as number, t.gps_start_lon as number]);
    if (selectedRoute) {
      for (const s of selectedRoute.stops) {
        if (s.latitude != null && s.longitude != null) pts.push([s.latitude, s.longitude]);
      }
    }
    return pts;
  }, [incoming, selectedRoute]);

  useEffect(() => {
    if (selectedRoute) {
      if (positions.length === 1) map.setView(positions[0], 13);
      else if (positions.length > 1) map.fitBounds(L.latLngBounds(positions), { padding: [40, 40] });
      return;
    }
    if (positions.length > 0) map.fitBounds(L.latLngBounds(positions), { padding: [40, 40], maxZoom: 13 });
    else map.setView(HYDERABAD_CENTER, 11);
  }, [map, positions, selectedRoute]);

  return null;
}

/** Dashed rectangle showing the Hyderabad service boundary. */
function RectangleBounds() {
  const map = useMap();
  useEffect(() => {
    const bounds = L.latLngBounds(
      [HYDERABAD_BOUNDS.minLat, HYDERABAD_BOUNDS.minLon],
      [HYDERABAD_BOUNDS.maxLat, HYDERABAD_BOUNDS.maxLon],
    );
    const rect = L.rectangle(bounds, {
      color: "#94a3b8",
      weight: 1.5,
      dashArray: "6 6",
      fill: false,
    }).addTo(map);
    return () => {
      rect.remove();
    };
  }, [map]);
  return null;
}

interface LiveOpsMapProps {
  incomingTrips: Trip[];
  routes: Route[];
  selectedRouteId: string | null;
  onSelectRoute: (routeId: string | null) => void;
  onSelectTrip: (tripId: string) => void;
  flights?: AssignmentFlight[];
}

function stopIcon(color: string, seq: number) {
  // Cached per (color, sequence) — static, never re-created.
  return cachedIcon(`stop-${color}-${seq}`, () =>
    L.divIcon({
      className: "",
      html: `<div style="background:${color};color:#fff;border:2px solid #fff;border-radius:9999px;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;box-shadow:0 1px 2px rgba(0,0,0,0.3);cursor:pointer">${seq}</div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    }),
  );
}

export function LiveOpsMap({ incomingTrips, routes, selectedRouteId, onSelectRoute, onSelectTrip, flights = [] }: LiveOpsMapProps) {
  const selectedRoute = routes.find((r) => r.route_id === selectedRouteId) ?? null;
  const visibleRoutes = selectedRoute ? [selectedRoute] : routes;

  // Clickable legend filter: which layer(s) the map shows.
  const [view, setView] = useState<"incoming" | "assigned" | "routes">("routes");
  const showRoutes = view === "routes";
  const showIncoming = view === "incoming";
  const showAssigned = view === "assigned";

  return (
    <div className="relative rounded-xl border border-slate-700/60 overflow-hidden bg-slate-900 dark-map">
      <MapContainer
        center={HYDERABAD_CENTER}
        zoom={11}
        minZoom={9}
        maxBounds={L.latLngBounds(
          [HYDERABAD_BOUNDS.minLat - 0.5, HYDERABAD_BOUNDS.minLon - 0.5],
          [HYDERABAD_BOUNDS.maxLat + 0.5, HYDERABAD_BOUNDS.maxLon + 0.5],
        )}
        style={{ height: 480, width: "100%" }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds incoming={incomingTrips} selectedRoute={selectedRoute} />
        <RectangleBounds />

        {/* Assignment flight-lines: animated trip -> route connection */}
        {(showAssigned || showRoutes) && flights.map((f) => (
          <Polyline
            key={f.id}
            positions={[f.from, f.to]}
            pathOptions={{ color: f.color, weight: 2.5, className: "flight-line" }}
          />
        ))}

        {showRoutes && visibleRoutes.map((route) => {
          const points = route.stops
            .filter((s) => s.latitude != null && s.longitude != null)
            .map((s) => [s.latitude as number, s.longitude as number] as [number, number]);
          if (points.length === 0) return null;
          const color = colorForRouteId(route.route_id);
          return (
            <div key={route.route_id}>
              <Polyline
                positions={points}
                pathOptions={{ color, weight: selectedRoute ? 4 : 2.5, opacity: 0.85 }}
                eventHandlers={{ click: () => onSelectRoute(route.route_id) }}
              />
              {route.stops.map((s, i) =>
                s.latitude == null || s.longitude == null ? null : (
                  <Marker
                    key={s.stop_id}
                    position={[s.latitude, s.longitude]}
                    icon={stopIcon(color, s.sequence ?? i + 1)}
                    eventHandlers={{ click: () => onSelectRoute(route.route_id) }}
                  >
                    <Tooltip direction="top" offset={[0, -12]}>
                      {`#${s.sequence ?? i + 1} ${s.stop_type}${s.trip_id ? ` — ${s.trip_id}` : ""} (click for details)`}
                    </Tooltip>
                  </Marker>
                ),
              )}
            </div>
          );
        })}

        {showIncoming && incomingTrips.map((t) =>
          t.gps_start_lat == null || t.gps_start_lon == null ? null : (
            <Marker
              key={t.trip_id}
              position={[t.gps_start_lat, t.gps_start_lon]}
              icon={incomingIcon()}
              eventHandlers={{ click: () => onSelectTrip(t.trip_id) }}
            >
              <Tooltip direction="top" offset={[0, -10]}>
                {`INCOMING ${t.trip_id} — ${t.origin ?? "?"} → ${t.destination ?? "?"} (click for details)`}
              </Tooltip>
            </Marker>
          ),
        )}

        {(showIncoming || showRoutes) && incomingTrips.map((t) =>
          t.gps_end_lat == null || t.gps_end_lon == null ? null : (
            <CircleMarker
              key={`${t.trip_id}-drop`}
              center={[t.gps_end_lat, t.gps_end_lon]}
              radius={6}
              pathOptions={{ color: "#f59e0b", fillOpacity: 0.15, weight: 2 }}
              eventHandlers={{ click: () => onSelectTrip(t.trip_id) }}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                {`Drop-off — ${t.destination ?? t.trip_id}`}
              </Tooltip>
            </CircleMarker>
          ),
        )}
      </MapContainer>

      <div className="absolute top-2 right-2 z-[1000] flex flex-col gap-1.5 px-3 py-2 rounded-lg bg-slate-900/90 border border-slate-700 text-xs text-slate-300 shadow-lg backdrop-blur">
        <button
          onClick={() => setView("incoming")}
          className={`flex items-center gap-2 text-left ${view === "incoming" ? "text-amber-300" : "hover:text-amber-300"}`}
          title="Show only incoming trips"
        >
          <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
          <span>Incoming (unassigned)</span>
          <span className="ml-auto tnum">{(incomingTrips.length)}</span>
        </button>
        <button
          onClick={() => setView("assigned")}
          className={`flex items-center gap-2 text-left ${view === "assigned" ? "text-teal-300" : "hover:text-teal-300"}`}
          title="Show assignment flights"
        >
          <span className="w-4 h-0.5 bg-teal-300" />
          <span>Assignment flights</span>
          <span className="ml-auto tnum">{flights.length}</span>
        </button>
        <button
          onClick={() => setView("routes")}
          className={`flex items-center gap-2 text-left ${view === "routes" ? "text-sky-300" : "hover:text-sky-300"}`}
          title="Show all routes"
        >
          <span className="w-4 h-0.5" style={{ background: colorForRouteId(routes[0]?.route_id ?? "0") }} />
          <span>Routes — one color each</span>
          <span className="ml-auto tnum">{routes.length}</span>
          {selectedRoute && ` · ${selectedRoute.name ?? selectedRoute.route_id.slice(0, 8)}`}
        </button>
        {selectedRoute && (
          <button onClick={() => onSelectRoute(null)} className="mt-1 text-left text-teal-300 font-medium hover:underline">
            Show all routes
          </button>
        )}
      </div>
    </div>
  );
}