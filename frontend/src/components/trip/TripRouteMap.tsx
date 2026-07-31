import { useEffect } from "react";
import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import type { StopProgress, StopProgressStatus } from "@/utils/stopProgress";
import { stopProgressMarkerColor } from "@/utils/stopProgress";

function numberedIcon(n: number, status: StopProgressStatus) {
  const color = stopProgressMarkerColor[status];
  const filled = status !== "pending";
  const bg = filled ? color : "#fff";
  const fg = filled ? "#fff" : color;
  const border = color;

  return L.divIcon({
    className: "",
    html: `<div style="background:${bg};border:2px solid ${border};color:${fg};border-radius:9999px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,0.25)">${n}</div>`,
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

interface TripRouteMapProps {
  stopProgress: StopProgress[];
  plannedGeometry: [number, number][] | null;
  actualTrace: [number, number][];
  stopCount: number;
}

export function TripRouteMap({ stopProgress, plannedGeometry, actualTrace, stopCount }: TripRouteMapProps) {
  const stopPositions: [number, number][] = stopProgress
    .filter(({ stop }) => stop.latitude != null && stop.longitude != null)
    .map(({ stop }) => [stop.latitude as number, stop.longitude as number]);

  const allPositions = [...stopPositions, ...actualTrace];

  if (stopPositions.length === 0) {
    return (
      <div className="flex-1 min-h-[280px] rounded-xl border border-gray-200 bg-gray-50 flex items-center justify-center text-sm text-gray-400">
        This route's stops aren't geocoded yet.
      </div>
    );
  }

  return (
    <div className="relative flex-1 min-h-[280px] rounded-xl border border-gray-200 overflow-hidden">
      <MapContainer
        center={stopPositions[0]}
        zoom={11}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds positions={allPositions} />

        {plannedGeometry && plannedGeometry.length > 1 && (
          <Polyline positions={plannedGeometry} pathOptions={{ color: "#3b82f6", weight: 3, dashArray: "6 6" }} />
        )}
        {actualTrace.length > 1 && (
          <Polyline positions={actualTrace} pathOptions={{ color: "#ef4444", weight: 3 }} />
        )}

        {stopProgress.map(({ stop, status }, index) => {
          if (stop.latitude == null || stop.longitude == null) return null;
          return (
            <Marker key={stop.stop_id} position={[stop.latitude, stop.longitude]} icon={numberedIcon(index + 1, status)}>
              <Tooltip permanent direction="top" offset={[0, -14]}>
                {stop.address ?? `Stop ${index + 1}`}
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>

      <div className="absolute bottom-2 left-2 z-[1000] flex items-center gap-3 px-3 py-1.5 rounded-lg bg-white/90 border border-gray-200 text-xs text-gray-500 shadow-sm">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 border-t-2 border-dashed border-blue-500" />
          Planned
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 border-t-2 border-red-500" />
          Actual GPS {actualTrace.length === 0 && "(no data)"}
        </span>
        <span>{stopCount} stops</span>
      </div>
    </div>
  );
}
