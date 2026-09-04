import { useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createTrip } from "@/api/trips";
import { geocodeAddress } from "@/api/geocode";
import { useRoadRoute } from "@/hooks/useRoadRoute";
import { RouteMapPreview, type StopType } from "./RouteMapPreview";
import {
  IconMapPin,
  IconX,
} from "@/components/common/icons";

interface CreateTripModalProps {
  open: boolean;
  onClose: () => void;
}

type PointRole = "pickup" | "drop";

interface PointForm {
  role: PointRole;
  locationName: string;
  addressDetail: string;
  latitude: number | null;
  longitude: number | null;
  errorRadius: number | null;
  geocodeStatus: "idle" | "loading" | "success" | "error";
}

const initialPoint = (role: PointRole): PointForm => ({
  role,
  locationName: "",
  addressDetail: "",
  latitude: null,
  longitude: null,
  errorRadius: null,
  geocodeStatus: "idle",
});

function pointAddress(point: PointForm): string {
  return [point.locationName, point.addressDetail].filter(Boolean).join(", ");
}

export function CreateTripModal({ open, onClose }: CreateTripModalProps) {
  const [pickup, setPickup] = useState<PointForm>(initialPoint("pickup"));
  const [drop, setDrop] = useState<PointForm>(initialPoint("drop"));
  const queryClient = useQueryClient();

  const mapStops = useMemo(() => {
    const result: { key: string; lat: number; lng: number; label: string; sequence: number; type: StopType }[] = [];
    
    // Depot at pickup location (for trip creation, depot = pickup location)
    if (pickup.latitude != null && pickup.longitude != null) {
      result.push({
        key: "depot",
        lat: pickup.latitude,
        lng: pickup.longitude,
        label: "Depot (Start)",
        sequence: 0,
        type: "depot",
      });
    }
    
    if (pickup.latitude != null && pickup.longitude != null) {
      result.push({
        key: "pickup",
        lat: pickup.latitude,
        lng: pickup.longitude,
        label: pickup.locationName || "Pickup",
        sequence: 1,
        type: "pickup",
      });
    }
    if (drop.latitude != null && drop.longitude != null) {
      result.push({
        key: "drop",
        lat: drop.latitude,
        lng: drop.longitude,
        label: drop.locationName || "Drop",
        sequence: 2,
        type: "delivery",
      });
    }
    return result;
  }, [pickup, drop]);

  const roadRoute = useRoadRoute(mapStops.map((s) => [s.lat, s.lng] as [number, number]));

  const updateAddressField = (role: PointRole, patch: Partial<PointForm>) => {
    const base = { ...patch, latitude: null, longitude: null, errorRadius: null, geocodeStatus: "idle" as const };
    if (role === "pickup") {
      setPickup((prev) => ({ ...prev, ...base }));
    } else {
      setDrop((prev) => ({ ...prev, ...base }));
    }
  };

  const locatePoint = async (point: PointForm, setter: (p: PointForm) => void) => {
    const address = pointAddress(point);
    if (!address) return;

    setter({ ...point, geocodeStatus: "loading" });
    try {
      const result = await geocodeAddress(address);
      setter({
        ...point,
        latitude: result.lat,
        longitude: result.lng,
        errorRadius: result.error_radius,
        geocodeStatus: "success",
      });
    } catch {
      setter({ ...point, geocodeStatus: "error" });
    }
  };

  const bothGeocoded = pickup.latitude != null && pickup.longitude != null && drop.latitude != null && drop.longitude != null;
  // planned_distance_km feeds delay/expected-delay/fuel-cost ML predictions
  // directly - a trip saved without it permanently fails those predictions
  // later (nothing backfills this field once the trip exists), so trip
  // creation is blocked until the road route actually resolves, not just geocoded.
  const readyToCreate = bothGeocoded && roadRoute.distanceKm != null;

  const mutation = useMutation({
    mutationFn: async () => {
      if (!readyToCreate) throw new Error("Route distance must be resolved before creating this trip");
      return createTrip({
        origin: pointAddress(pickup),
        destination: pointAddress(drop),
        gps_start_lat: pickup.latitude,
        gps_start_lon: pickup.longitude,
        gps_end_lat: drop.latitude,
        gps_end_lon: drop.longitude,
        planned_distance_km: roadRoute.distanceKm,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      resetAndClose();
    },
  });

  if (!open) return null;

  const resetAndClose = () => {
    setPickup(initialPoint("pickup"));
    setDrop(initialPoint("drop"));
    onClose();
  };

  const mutationErrorMessage =
    mutation.isError && isAxiosError(mutation.error) && typeof mutation.error.response?.data?.detail === "string"
      ? mutation.error.response.data.detail
      : mutation.isError
        ? "Something went wrong creating this trip. Please try again."
        : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="flex items-start justify-between px-6 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Create Trip</h2>
            <p className="text-sm text-gray-500 mt-0.5">Enter pickup and drop locations to create a new shipment.</p>
          </div>
          <button onClick={resetAndClose} className="text-gray-400 hover:text-gray-600">
            <IconX />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-6">
            <PointEditor
              point={pickup}
              onChange={updateAddressField}
              onLocate={locatePoint}
              setter={setPickup}
              label="Pickup"
              iconColor="bg-sky-100 text-sky-700"
            />
            <PointEditor
              point={drop}
              onChange={updateAddressField}
              onLocate={locatePoint}
              setter={setDrop}
              label="Drop"
              iconColor="bg-emerald-100 text-emerald-700"
            />
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex flex-col h-[320px]">
              <RouteMapPreview
                stops={mapStops}
                routeGeometry={roadRoute.geometry}
                isRouteLoading={roadRoute.isLoading}
                isRouteError={roadRoute.isError}
                emptyLabel="Locate pickup and drop to preview them on the map"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <SummaryStat
                label="Distance"
                value={roadRoute.distanceKm != null ? `${Math.round(roadRoute.distanceKm)} km` : "—"}
              />
              <SummaryStat
                label="Est. duration"
                value={roadRoute.durationHours != null ? `${roadRoute.durationHours.toFixed(1)} h` : "—"}
              />
            </div>
            {bothGeocoded && roadRoute.isLoading && (
              <p className="text-xs text-gray-500">Calculating route distance…</p>
            )}
            {bothGeocoded && roadRoute.distanceKm == null && !roadRoute.isLoading && (
              <p className="text-xs text-red-600">
                Couldn't calculate a route distance for these points — try re-locating pickup or drop. A trip can't
                be created without it (delay/fuel predictions depend on this field).
              </p>
            )}
          </div>
        </div>

        {mutationErrorMessage && (
          <div className="mx-6 mb-3 px-4 py-2.5 rounded-lg bg-red-50 border border-red-100 text-sm text-red-700">
            {mutationErrorMessage}
          </div>
        )}

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100">
          <button onClick={resetAndClose} className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !readyToCreate}
            title={bothGeocoded && !readyToCreate ? "Waiting for route distance to resolve" : undefined}
            className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Creating…" : "Create Trip"}
          </button>
        </div>
      </div>
    </div>
  );
}

interface PointEditorProps {
  point: PointForm;
  onChange: (role: PointRole, patch: Partial<PointForm>) => void;
  onLocate: (point: PointForm, setter: (p: PointForm) => void) => void;
  setter: (p: PointForm) => void;
  label: string;
  iconColor: string;
}

function PointEditor({ point, onChange, onLocate, setter, label, iconColor }: PointEditorProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold ${iconColor}`}>
          <IconMapPin />
        </span>
        <h3 className="text-lg font-semibold text-gray-900">{label}</h3>
      </div>

      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Location Name</label>
          <input
            type="text"
            placeholder={label === "pickup" ? "e.g. Rotterdam" : "e.g. Utrecht"}
            value={point.locationName}
            onChange={(e) => onChange(point.role, { locationName: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Address Detail</label>
          <input
            type="text"
            placeholder={label === "pickup" ? "e.g. Maasvlakte Terminal 4" : "e.g. City Center Warehouse"}
            value={point.addressDetail}
            onChange={(e) => onChange(point.role, { addressDetail: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onLocate(point, setter)}
            disabled={!pointAddress(point) || point.geocodeStatus === "loading"}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-gray-200 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <IconMapPin className={point.geocodeStatus === "loading" ? "animate-pulse" : ""} />
            {point.geocodeStatus === "loading" ? "Locating…" : "Locate"}
          </button>

          {point.geocodeStatus === "success" && point.latitude != null && point.longitude != null && (
            <span className="text-xs text-emerald-600">
              📍 {point.latitude.toFixed(4)}, {point.longitude.toFixed(4)}
              {point.errorRadius != null && ` (±${point.errorRadius}m)`}
            </span>
          )}
          {point.geocodeStatus === "error" && (
            <span className="text-xs text-red-600">Couldn't locate this address</span>
          )}
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