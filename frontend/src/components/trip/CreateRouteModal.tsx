import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createRoute, optimizeRouteOrder } from "@/api/routes";
import { geocodeAddress } from "@/api/geocode";
import { useRoadRoute } from "@/hooks/useRoadRoute";
import { useToast } from "@/components/common/Toast";
import { RouteMapPreview } from "./RouteMapPreview";
import type { StopType } from "@/types/route";
import {
  IconArrowDown,
  IconArrowUp,
  IconMapPin,
  IconPlus,
  IconSparkle,
  IconTrash,
  IconX,
} from "@/components/common/icons";

interface CreateRouteModalProps {
  open: boolean;
  onClose: () => void;
  tripId?: string;
}

type GeocodeStatus = "idle" | "loading" | "success" | "error";

interface StopForm {
  key: string;
  locationName: string;
  addressDetail: string;
  stopType: StopType;
  latitude: number | null;
  longitude: number | null;
  errorRadius: number | null;
  geocodeStatus: GeocodeStatus;
}

const stopTypeOptions: { value: StopType; label: string }[] = [
  { value: "pickup", label: "Pickup" },
  { value: "waypoint", label: "Waypoint" },
  { value: "delivery", label: "Delivery" },
];

function makeStop(): StopForm {
  return {
    key: crypto.randomUUID(),
    locationName: "",
    addressDetail: "",
    stopType: "waypoint",
    latitude: null,
    longitude: null,
    errorRadius: null,
    geocodeStatus: "idle",
  };
}

function stopAddress(stop: StopForm): string {
  return [stop.locationName, stop.addressDetail].filter(Boolean).join(", ");
}

// No real toll-cost API is wired in — this stays a per-km heuristic on top of the real OSRM distance.
const TOLL_RATE_PER_KM_INR = 2;

export function CreateRouteModal({ open, onClose, tripId }: CreateRouteModalProps) {
  const [stops, setStops] = useState<StopForm[]>([makeStop(), makeStop()]);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [optimizeError, setOptimizeError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const mutation = useMutation({
    mutationFn: () =>
      createRoute({
        trip_id: tripId,
        stops: stops.map((stop, index) => ({
          sequence: index + 1,
          address: stopAddress(stop),
          latitude: stop.latitude,
          longitude: stop.longitude,
          stop_type: stop.stopType,
        })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["routes"] });
      setStops([makeStop(), makeStop()]);
      onClose();
    },
  });

  const geocodedPositions: [number, number][] = stops
    .filter((s) => s.latitude != null && s.longitude != null)
    .map((s) => [s.latitude as number, s.longitude as number]);

  const roadRoute = useRoadRoute(geocodedPositions);

  if (!open) return null;

  const addStop = () => setStops((prev) => [...prev, makeStop()]);
  const removeStop = (key: string) => setStops((prev) => prev.filter((s) => s.key !== key));
  const updateStop = (key: string, patch: Partial<StopForm>) =>
    setStops((prev) => prev.map((s) => (s.key === key ? { ...s, ...patch } : s)));

  // Editing the address after a successful geocode invalidates the coordinates —
  // lat/lon must only ever come from a real geocode response, never a stale one.
  const updateAddressField = (key: string, patch: Partial<StopForm>) =>
    setStops((prev) =>
      prev.map((s) =>
        s.key === key
          ? { ...s, ...patch, latitude: null, longitude: null, errorRadius: null, geocodeStatus: "idle" }
          : s,
      ),
    );

  const moveStop = (index: number, direction: -1 | 1) => {
    setStops((prev) => {
      const target = index + direction;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const locateStop = async (stop: StopForm) => {
    const address = stopAddress(stop);
    if (!address) return;

    updateStop(stop.key, { geocodeStatus: "loading" });
    try {
      const result = await geocodeAddress(address);
      updateStop(stop.key, {
        latitude: result.lat,
        longitude: result.lng,
        errorRadius: result.error_radius,
        geocodeStatus: "success",
      });
    } catch {
      updateStop(stop.key, { geocodeStatus: "error" });
    }
  };

  const allStopsGeocoded = stops.length >= 2 && stops.every((s) => s.latitude != null && s.longitude != null);

  const optimizeRoute = async () => {
    if (!allStopsGeocoded) return;

    // Snapshot the current (pre-optimization) real road-route numbers to diff against the result.
    const beforeDistanceKm = roadRoute.distanceKm;
    const beforeDurationHours = roadRoute.durationHours;

    setIsOptimizing(true);
    setOptimizeError(null);
    try {
      const result = await optimizeRouteOrder(
        stops.map((s) => ({ key: s.key, latitude: s.latitude as number, longitude: s.longitude as number })),
      );
      const byKey = new Map(stops.map((s) => [s.key, s]));
      const reordered = result.order
        .map((key) => byKey.get(key))
        .filter((s): s is StopForm => s !== undefined);
      setStops(reordered);

      const afterDistanceKm = result.total_distance_meters / 1000;
      const afterDurationMin = result.total_duration_seconds / 60;

      if (beforeDistanceKm != null && beforeDurationHours != null) {
        const savedDistanceKm = beforeDistanceKm - afterDistanceKm;
        const savedMinutes = beforeDurationHours * 60 - afterDurationMin;

        if (savedDistanceKm > 0.5 || savedMinutes > 0.5) {
          showToast(
            `Route optimized: saved ${savedDistanceKm > 0.5 ? `${Math.round(savedDistanceKm)} km` : ""}${
              savedDistanceKm > 0.5 && savedMinutes > 0.5 ? " and " : ""
            }${savedMinutes > 0.5 ? `${Math.round(savedMinutes)} min` : ""}`,
            "success",
          );
        } else {
          showToast("Route optimized — this order was already the fastest.", "info");
        }
      } else {
        showToast("Route optimized.", "success");
      }
    } catch {
      setOptimizeError("Couldn't optimize the route. Try again.");
      showToast("Couldn't optimize the route. Try again.", "error");
    } finally {
      setIsOptimizing(false);
    }
  };

  const totalDistanceKm = roadRoute.distanceKm ?? 0;
  const estDurationHours = roadRoute.durationHours ?? 0;
  const estTolls = totalDistanceKm * TOLL_RATE_PER_KM_INR;
  const hasUngeocodedStops = stops.length > 1 && geocodedPositions.length < stops.length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="flex items-start justify-between px-6 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Create multi-stop route</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Add stops, reorder them, and let the optimizer find the best sequence.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <IconX />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <button
                onClick={addStop}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700"
              >
                <IconPlus />
                Add stop
              </button>
              <button
                onClick={optimizeRoute}
                disabled={!allStopsGeocoded || isOptimizing}
                title={!allStopsGeocoded ? "Locate every stop first to enable optimization" : undefined}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <IconSparkle className={isOptimizing ? "animate-spin" : ""} />
                {isOptimizing ? "Optimizing…" : "Optimize route"}
              </button>
            </div>
            {optimizeError && <p className="text-xs text-red-600">{optimizeError}</p>}

            <div className="space-y-3">
              {stops.map((stop, index) => (
                <div key={stop.key} className="border border-gray-200 rounded-xl p-3">
                  <div className="flex items-start gap-3">
                    <span className="w-6 h-6 rounded-full bg-sky-100 text-sky-700 text-xs font-semibold flex items-center justify-center shrink-0 mt-0.5">
                      {index + 1}
                    </span>

                    <div className="flex-1 space-y-2">
                      <input
                        placeholder="Location name (e.g. Rotterdam)"
                        className="w-full text-sm font-medium text-gray-900 border-b border-transparent focus:border-gray-300 focus:outline-none py-0.5"
                        value={stop.locationName}
                        onChange={(e) => updateAddressField(stop.key, { locationName: e.target.value })}
                      />
                      <input
                        placeholder="Address detail (e.g. Maasvlakte Terminal 4)"
                        className="w-full text-sm text-gray-500 border-b border-transparent focus:border-gray-300 focus:outline-none py-0.5"
                        value={stop.addressDetail}
                        onChange={(e) => updateAddressField(stop.key, { addressDetail: e.target.value })}
                      />

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => locateStop(stop)}
                          disabled={!stopAddress(stop) || stop.geocodeStatus === "loading"}
                          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-gray-200 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <IconMapPin className={stop.geocodeStatus === "loading" ? "animate-pulse" : ""} />
                          {stop.geocodeStatus === "loading" ? "Locating…" : "Locate"}
                        </button>

                        {stop.geocodeStatus === "success" && stop.latitude != null && stop.longitude != null && (
                          <span className="text-xs text-emerald-600">
                            📍 {stop.latitude.toFixed(4)}, {stop.longitude.toFixed(4)}
                            {stop.errorRadius != null && ` (±${stop.errorRadius}m)`}
                          </span>
                        )}
                        {stop.geocodeStatus === "error" && (
                          <span className="text-xs text-red-600">Couldn't locate this address</span>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <select
                          value={stop.stopType}
                          onChange={(e) => updateStop(stop.key, { stopType: e.target.value as StopType })}
                          className="px-2.5 py-1.5 rounded-lg border border-gray-200 text-sm text-gray-700 bg-white"
                        >
                          {stopTypeOptions.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div className="flex flex-col gap-1 shrink-0">
                      <button
                        onClick={() => moveStop(index, -1)}
                        disabled={index === 0}
                        className="p-1.5 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <IconArrowUp />
                      </button>
                      <button
                        onClick={() => moveStop(index, 1)}
                        disabled={index === stops.length - 1}
                        className="p-1.5 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <IconArrowDown />
                      </button>
                      <button
                        onClick={() => removeStop(stop.key)}
                        className="p-1.5 rounded-md border border-gray-200 text-red-500 hover:bg-red-50"
                      >
                        <IconTrash />
                      </button>
                    </div>
                  </div>
                </div>
              ))}

              {stops.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-6">No stops yet — add one to get started.</p>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-4">
            <RouteMapPreview
              stops={stops
                .map((stop, index) => ({ stop, sequence: index + 1 }))
                .filter(({ stop }) => stop.latitude != null && stop.longitude != null)
                .map(({ stop, sequence }) => ({
                  key: stop.key,
                  lat: stop.latitude as number,
                  lng: stop.longitude as number,
                  label: stop.locationName || `Stop ${sequence}`,
                  sequence,
                }))}
              routeGeometry={roadRoute.geometry}
              isRouteLoading={roadRoute.isLoading}
              isRouteError={roadRoute.isError}
            />

            <div className="grid grid-cols-3 gap-3">
              <SummaryStat label="Total distance" value={`${Math.round(totalDistanceKm)} km`} />
              <SummaryStat label="Est. duration" value={`${estDurationHours.toFixed(1)} h`} />
              <SummaryStat label="Est. tolls" value={`₹${Math.round(estTolls)}`} />
            </div>
            {hasUngeocodedStops && (
              <p className="text-xs text-amber-600 -mt-2">
                Locate every stop to include it in the route distance/duration calculation.
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || stops.length === 0}
            className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Saving…" : "Save route"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-gray-200 rounded-xl p-3">
      <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-1">{label}</div>
      <div className="text-lg font-semibold text-gray-900">{value}</div>
    </div>
  );
}

