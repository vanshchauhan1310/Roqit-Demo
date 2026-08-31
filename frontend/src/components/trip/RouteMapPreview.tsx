import { useEffect } from "react";
import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";

export type StopType = "depot" | "pickup" | "delivery";

function depotIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="background:#fff;border:2px solid #22c55e;color:#22c55e;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;box-shadow:0 1px 2px rgba(0,0,0,0.25)">🏭</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function pickupIcon(n: number) {
  return L.divIcon({
    className: "",
    html: `<div style="background:#fff;border:2px solid #3b82f6;color:#3b82f6;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,0.25)">${n}</div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

function deliveryIcon(n: number) {
  return L.divIcon({
    className: "",
    html: `<div style="background:#3b82f6;border:2px solid #1d4ed8;color:#fff;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,0.25)">${n}</div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

export interface MapStop {
  key: string;
  lat: number;
  lng: number;
  label: string;
  sequence: number;
  type: StopType;
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

interface RouteMapPreviewProps {
  stops: MapStop[];
  routeGeometry: [number, number][] | null;
  isRouteLoading: boolean;
  isRouteError: boolean;
  emptyLabel?: string;
}

export function RouteMapPreview({ stops, routeGeometry, isRouteLoading, isRouteError, emptyLabel }: RouteMapPreviewProps) {
  const positions: [number, number][] = stops.map((s) => [s.lat, s.lng]);

  if (stops.length === 0) {
    return (
      <div className="flex-1 min-h-[220px] rounded-xl border border-gray-200 bg-gray-50 flex items-center justify-center text-sm text-gray-400">
        {emptyLabel ?? "Locate stops to preview them on the map"}
      </div>
    );
  }

  return (
    <div className="relative flex-1 min-h-[220px] rounded-xl border border-gray-200 overflow-hidden">
      <MapContainer center={positions[0]} zoom={11} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds positions={positions} />
        {routeGeometry && routeGeometry.length > 1 && (
          <Polyline positions={routeGeometry} pathOptions={{ color: "#0ea5e9", weight: 4 }} />
        )}
        {stops.map((stop) => {
          let icon;
          switch (stop.type) {
            case "depot":
              icon = depotIcon();
              break;
            case "pickup":
              icon = pickupIcon(stop.sequence);
              break;
            case "delivery":
              icon = deliveryIcon(stop.sequence);
              break;
            default:
              icon = pickupIcon(stop.sequence);
          }
          return (
            <Marker key={stop.key} position={[stop.lat, stop.lng]} icon={icon}>
              <Tooltip permanent direction="top" offset={[0, -14]}>
                {stop.label}
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>

      <div className="absolute bottom-2 left-2 z-[1000] flex items-center gap-2 px-2 py-1 rounded-md bg-white/90 border border-gray-200 text-xs text-gray-500 shadow-sm">
        <span className="flex items-center gap-1">
          <span style={{width: 12, height: 12, borderRadius: '50%', border: '2px solid #22c55e', display: 'inline-flex', alignItems: 'center', justifyContent: 'center'}}>🏭</span>
          Depot
        </span>
        <span className="flex items-center gap-1">
          <span style={{width: 10, height: 10, borderRadius: '50%', border: '2px solid #3b82f6', background: '#fff', display: 'inline-block'}}></span>
          Pickup
        </span>
        <span className="flex items-center gap-1">
          <span style={{width: 10, height: 10, borderRadius: '50%', border: '2px solid #1d4ed8', background: '#3b82f6', display: 'inline-block'}}></span>
          Delivery
        </span>
      </div>

      {positions.length > 1 && isRouteLoading && (
        <span className="absolute bottom-2 right-2 z-[1000] px-2 py-1 rounded-md bg-white/90 border border-gray-200 text-xs text-gray-500 shadow-sm">
          Calculating road route…
        </span>
      )}
      {positions.length > 1 && isRouteError && (
        <span className="absolute bottom-2 right-2 z-[1000] px-2 py-1 rounded-md bg-white/90 border border-gray-200 text-xs text-red-600 shadow-sm">
          Couldn't load the road route
        </span>
      )}
    </div>
  );
}
