import { useEffect } from "react";
import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";

/** One colour per vehicle route. Distinct hues rather than a gradient, since the
 *  job here is telling routes apart at a glance, not showing magnitude. */
export const ROUTE_COLORS = ["#0ea5e9", "#16a34a", "#d946ef", "#f59e0b", "#ef4444", "#6366f1"];

export function routeColor(index: number): string {
  return ROUTE_COLORS[index % ROUTE_COLORS.length];
}

export interface FleetMapStop {
  key: string;
  lat: number;
  lng: number;
  label: string;
  sequence: number;
  stopType: "pickup" | "delivery";
}

export interface FleetMapRoute {
  vehicleId: string;
  color: string;
  stops: FleetMapStop[];
  legs: FleetMapLeg[];
}

export interface FleetMapLeg {
  positions: [number, number][];
  carryingCargo: boolean;
}

/** Pickups are filled, deliveries hollow — preserving the pickup/delivery
 *  distinction the single-vehicle map already establishes, with the vehicle's
 *  colour carried through so a marker is traceable to its route. */
function stopIcon(n: number, color: string, stopType: "pickup" | "delivery") {
  const fill = stopType === "pickup" ? color : "#ffffff";
  const text = stopType === "pickup" ? "#ffffff" : color;
  return L.divIcon({
    className: "",
    html: `<div style="background:${fill};border:2px solid ${color};color:${text};border-radius:9999px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,0.25)">${n}</div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

function FitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length === 0) return;
    if (positions.length === 1) {
      map.setView(positions[0], 12);
    } else {
      map.fitBounds(L.latLngBounds(positions), { padding: [30, 30] });
    }
  }, [map, positions]);
  return null;
}

interface FleetRouteMapProps {
  routes: FleetMapRoute[];
  emptyLabel?: string;
}

export function FleetRouteMap({ routes, emptyLabel }: FleetRouteMapProps) {
  const allPositions: [number, number][] = routes.flatMap((r) => r.stops.map((s) => [s.lat, s.lng] as [number, number]));

  if (allPositions.length === 0) {
    return (
      <div className="flex-1 min-h-[260px] rounded-xl border border-gray-200 bg-gray-50 flex items-center justify-center text-sm text-gray-400">
        {emptyLabel ?? "Optimize to see each vehicle's route"}
      </div>
    );
  }

  return (
    <div className="relative flex-1 min-h-[260px] rounded-xl border border-gray-200 overflow-hidden">
      <MapContainer center={allPositions[0]} zoom={11} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds positions={allPositions} />

        {routes.flatMap((route) =>
          route.legs.map((leg, index) => (
            <Polyline
              key={`${route.vehicleId}-leg-${index}`}
              positions={leg.positions}
              pathOptions={{
                color: route.color,
                weight: leg.carryingCargo ? 5 : 3,
                opacity: leg.carryingCargo ? 0.9 : 0.6,
                dashArray: leg.carryingCargo ? undefined : "7 8",
              }}
            >
              <Tooltip sticky>{leg.carryingCargo ? "Carrying cargo" : "Repositioning — no cargo on board"}</Tooltip>
            </Polyline>
          )),
        )}

        {routes.map((route) =>
          route.stops.map((stop) => (
            <Marker
              key={`${route.vehicleId}-${stop.key}`}
              position={[stop.lat, stop.lng]}
              icon={stopIcon(stop.sequence, route.color, stop.stopType)}
            >
              <Tooltip direction="top" offset={[0, -14]}>
                <span className="font-medium">{route.vehicleId}</span> · {stop.label}
              </Tooltip>
            </Marker>
          )),
        )}
      </MapContainer>

      {routes.length > 0 && (
        <div className="absolute bottom-2 left-2 z-[1000] flex flex-wrap gap-x-3 gap-y-1 px-2.5 py-1.5 rounded-md bg-white/95 border border-gray-200 shadow-sm">
          {routes.map((route) => (
            <span key={route.vehicleId} className="flex items-center gap-1.5 text-xs text-gray-700">
              <span className="w-3 h-1 rounded-full" style={{ backgroundColor: route.color }} />
              {route.vehicleId}
            </span>
          ))}
          <span className="flex items-center gap-1.5 text-xs text-gray-700 border-l border-gray-200 pl-3">
            <span className="w-4 h-1 rounded-full bg-gray-500" /> Carrying cargo
          </span>
          <span className="flex items-center gap-1.5 text-xs text-gray-700">
            <span className="w-4 border-t-2 border-dashed border-gray-500" /> Repositioning
          </span>
        </div>
      )}
    </div>
  );
}
