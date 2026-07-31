import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createTrip } from "@/api/trips";
import { assignRouteToTrip } from "@/api/routes";
import { useRoutes } from "@/hooks/useRoutes";
import { useDriverRoster } from "@/hooks/useDriverRoster";
import { useVehicleRoster } from "@/hooks/useVehicleRoster";
import { useRoadRoute, type RoadRoute } from "@/hooks/useRoadRoute";
import type { Route } from "@/types/route";
import type { DriverRosterItem, VehicleRosterItem } from "@/types/roster";
import {
  IconAlertTriangle,
  IconCheck,
  IconChevronDown,
  IconFuel,
  IconShield,
  IconStar,
  IconX,
} from "@/components/common/icons";

interface CreateTripModalProps {
  open: boolean;
  onClose: () => void;
  onBuildRoute: () => void;
}

const STEP_LABELS = ["Route", "Driver", "Vehicle", "Load", "Review"];
const LAST_STEP = STEP_LABELS.length - 1;

// No real cost-estimation model wired in — this stays a per-km heuristic.
const COST_PER_KM_INR = 15;

function routeEndpoints(route: Route): {
  origin: string;
  destination: string;
  stopCount: number;
  startLat: number | null;
  startLon: number | null;
  endLat: number | null;
  endLon: number | null;
} {
  const sorted = [...route.stops].sort((a, b) => a.sequence - b.sequence);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  return {
    origin: first?.address ?? "Unknown",
    destination: last?.address ?? "Unknown",
    stopCount: sorted.length,
    startLat: first?.latitude ?? null,
    startLon: first?.longitude ?? null,
    endLat: last?.latitude ?? null,
    endLon: last?.longitude ?? null,
  };
}

function routePositions(route: Route): [number, number][] {
  return [...route.stops]
    .sort((a, b) => a.sequence - b.sequence)
    .filter((s) => s.latitude != null && s.longitude != null)
    .map((s) => [s.latitude as number, s.longitude as number]);
}

export function CreateTripModal({ open, onClose, onBuildRoute }: CreateTripModalProps) {
  const [step, setStep] = useState(0);
  const [selectedRouteId, setSelectedRouteId] = useState("");
  const [selectedDriverId, setSelectedDriverId] = useState("");
  const [selectedVehicleId, setSelectedVehicleId] = useState("");
  const [loadWeightKg, setLoadWeightKg] = useState("");
  const [loadDescription, setLoadDescription] = useState("");
  const [loadValue, setLoadValue] = useState("");
  const [pickupDateTime, setPickupDateTime] = useState("");

  const queryClient = useQueryClient();
  const { data: routes, isLoading: routesLoading } = useRoutes();
  const { data: drivers, isLoading: driversLoading } = useDriverRoster();
  const { data: vehicles, isLoading: vehiclesLoading } = useVehicleRoster();

  const selectedRoute = routes?.find((r) => r.route_id === selectedRouteId) ?? null;
  const selectedDriver = drivers?.find((d) => d.driver_id === selectedDriverId) ?? null;
  const selectedVehicle = vehicles?.find((v) => v.vehicle_id === selectedVehicleId) ?? null;

  const positions = useMemo(() => (selectedRoute ? routePositions(selectedRoute) : []), [selectedRoute]);
  const roadRoute = useRoadRoute(positions);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!selectedRoute || !selectedDriver || !selectedVehicle) {
        throw new Error("Missing required selection");
      }
      const { origin, destination, startLat, startLon, endLat, endLon } = routeEndpoints(selectedRoute);
      const pickupIso = new Date(pickupDateTime).toISOString();
      const durationHours = roadRoute.durationHours ?? 0;
      const plannedDelivery = pickupDateTime
        ? new Date(new Date(pickupDateTime).getTime() + durationHours * 3600 * 1000).toISOString()
        : null;

      const trip = await createTrip({
        driver_id: selectedDriver.driver_id,
        driver_name: selectedDriver.driver_name,
        vehicle_id: selectedVehicle.vehicle_id,
        vehicle_type: selectedVehicle.vehicle_type,
        origin,
        destination,
        gps_start_lat: startLat,
        gps_start_lon: startLon,
        gps_end_lat: endLat,
        gps_end_lon: endLon,
        pickup_time: pickupIso,
        planned_delivery_time: plannedDelivery,
        planned_distance_km: roadRoute.distanceKm ?? null,
        load_weight_kg: loadWeightKg ? Number(loadWeightKg) : null,
        load_value: loadValue ? Number(loadValue) : null,
      });

      // Tie the selected route back to the trip it was actually used for.
      await assignRouteToTrip(selectedRoute.route_id, trip.trip_id);

      return trip;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      queryClient.invalidateQueries({ queryKey: ["routes"] });
      resetAndClose();
    },
  });

  if (!open) return null;

  const resetAndClose = () => {
    setStep(0);
    setSelectedRouteId("");
    setSelectedDriverId("");
    setSelectedVehicleId("");
    setLoadWeightKg("");
    setLoadDescription("");
    setLoadValue("");
    setPickupDateTime("");
    onClose();
  };

  const canContinue = (): boolean => {
    if (step === 0) return Boolean(selectedRoute);
    if (step === 1) return Boolean(selectedDriver);
    if (step === 2) return Boolean(selectedVehicle);
    if (step === 3) return loadWeightKg.trim() !== "";
    return true;
  };

  const totalDistanceKm = roadRoute.distanceKm ?? 0;
  const estCost = totalDistanceKm * COST_PER_KM_INR;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="flex items-start justify-between px-6 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Create trip</h2>
            <p className="text-sm text-gray-500 mt-0.5">Five quick steps to dispatch a new load.</p>
          </div>
          <button onClick={resetAndClose} className="text-gray-400 hover:text-gray-600">
            <IconX />
          </button>
        </div>

        <div className="px-6 pt-5">
          <StepIndicator current={step} />
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {step === 0 && (
            <RouteStep
              routes={routes ?? []}
              isLoading={routesLoading}
              selectedRouteId={selectedRouteId}
              onSelectRoute={setSelectedRouteId}
              roadRoute={roadRoute}
              hasSelection={Boolean(selectedRoute)}
              onBuildRoute={() => {
                resetAndClose();
                onBuildRoute();
              }}
            />
          )}
          {step === 1 && (
            <DriverStep
              drivers={drivers ?? []}
              isLoading={driversLoading}
              selectedDriverId={selectedDriverId}
              onSelectDriver={setSelectedDriverId}
            />
          )}
          {step === 2 && (
            <VehicleStep
              vehicles={vehicles ?? []}
              isLoading={vehiclesLoading}
              selectedVehicleId={selectedVehicleId}
              onSelectVehicle={setSelectedVehicleId}
            />
          )}
          {step === 3 && (
            <LoadStep
              loadWeightKg={loadWeightKg}
              onWeightChange={setLoadWeightKg}
              loadDescription={loadDescription}
              onDescriptionChange={setLoadDescription}
              loadValue={loadValue}
              onValueChange={setLoadValue}
            />
          )}
          {step === 4 && selectedRoute && selectedDriver && selectedVehicle && (
            <ReviewStep
              route={selectedRoute}
              driver={selectedDriver}
              vehicle={selectedVehicle}
              loadWeightKg={loadWeightKg}
              loadDescription={loadDescription}
              distanceKm={totalDistanceKm}
              estCost={estCost}
              pickupDateTime={pickupDateTime}
              onPickupDateTimeChange={setPickupDateTime}
            />
          )}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100">
          <button
            onClick={() => setStep((s) => Math.max(s - 1, 0))}
            disabled={step === 0}
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 disabled:text-gray-300 disabled:cursor-not-allowed"
          >
            Back
          </button>

          {step < LAST_STEP ? (
            <button
              onClick={() => setStep((s) => Math.min(s + 1, LAST_STEP))}
              disabled={!canContinue()}
              className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Continue
            </button>
          ) : (
            <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || !pickupDateTime}
              className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50"
            >
              {mutation.isPending ? "Scheduling…" : "Schedule trip"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center">
      {STEP_LABELS.map((label, i) => (
        <div key={label} className={`flex items-center ${i < STEP_LABELS.length - 1 ? "flex-1" : ""}`}>
          <div className="flex items-center gap-2">
            <span
              className={`w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold ${
                i < current
                  ? "bg-emerald-500 text-white"
                  : i === current
                    ? "bg-teal-600 text-white"
                    : "bg-gray-100 text-gray-400"
              }`}
            >
              {i < current ? <IconCheck /> : i + 1}
            </span>
            <span className={`text-sm font-medium whitespace-nowrap ${i <= current ? "text-gray-900" : "text-gray-400"}`}>
              {label}
            </span>
          </div>
          {i < STEP_LABELS.length - 1 && (
            <div className={`flex-1 h-px mx-3 ${i < current ? "bg-emerald-300" : "bg-gray-200"}`} />
          )}
        </div>
      ))}
    </div>
  );
}

interface RouteStepProps {
  routes: Route[];
  isLoading: boolean;
  selectedRouteId: string;
  onSelectRoute: (id: string) => void;
  roadRoute: RoadRoute;
  hasSelection: boolean;
  onBuildRoute: () => void;
}

function RouteStep({ routes, isLoading, selectedRouteId, onSelectRoute, roadRoute, hasSelection, onBuildRoute }: RouteStepProps) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-semibold text-gray-900 mb-2">Select an existing route</label>
        <div className="relative">
          <select
            value={selectedRouteId}
            onChange={(e) => onSelectRoute(e.target.value)}
            className="w-full appearance-none px-3 py-2.5 pr-9 rounded-lg border border-gray-200 bg-white text-sm text-gray-700"
          >
            <option value="">{isLoading ? "Loading routes…" : "Select a route"}</option>
            {routes.map((route) => {
              const { origin, destination, stopCount } = routeEndpoints(route);
              return (
                <option key={route.route_id} value={route.route_id}>
                  {origin} → {destination} ({stopCount} stops)
                </option>
              );
            })}
          </select>
          <IconChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        </div>
      </div>

      {hasSelection && (
        <div className="px-4 py-3 rounded-lg border border-gray-200 bg-gray-50 text-sm text-gray-600">
          {roadRoute.isLoading
            ? "Calculating distance…"
            : roadRoute.distanceKm != null && roadRoute.durationHours != null
              ? `${Math.round(roadRoute.distanceKm)} km · est. ${roadRoute.durationHours.toFixed(1)} h drive time`
              : "This route's stops aren't geocoded yet — distance unavailable"}
        </div>
      )}

      <button
        type="button"
        onClick={onBuildRoute}
        className="w-full px-4 py-2.5 rounded-lg border border-gray-200 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        Build a new multi-stop route instead
      </button>
    </div>
  );
}

function statusBadgeStyle(status: string | null): string {
  const s = (status ?? "").toLowerCase();
  if (s.includes("avail") || s.includes("active")) return "bg-emerald-50 text-emerald-700";
  if (s.includes("inactive") || s.includes("suspend")) return "bg-red-50 text-red-600";
  if (!s) return "bg-gray-100 text-gray-500";
  return "bg-amber-50 text-amber-700";
}

interface DriverStepProps {
  drivers: DriverRosterItem[];
  isLoading: boolean;
  selectedDriverId: string;
  onSelectDriver: (id: string) => void;
}

function DriverStep({ drivers, isLoading, selectedDriverId, onSelectDriver }: DriverStepProps) {
  return (
    <div>
      <label className="block text-sm font-semibold text-gray-900 mb-2">Assign driver</label>
      {isLoading && <p className="text-sm text-gray-400">Loading drivers…</p>}
      {!isLoading && drivers.length === 0 && <p className="text-sm text-gray-400">No drivers found.</p>}
      <div className="space-y-2">
        {drivers.map((driver) => {
          const selected = driver.driver_id === selectedDriverId;
          const unavailable = driver.is_on_trip;
          const subtitleParts = [
            driver.driver_id,
            driver.experience_years != null ? `${driver.experience_years} yrs` : null,
            driver.license_type,
          ].filter(Boolean);

          return (
            <button
              key={driver.driver_id}
              type="button"
              onClick={() => !unavailable && onSelectDriver(driver.driver_id)}
              disabled={unavailable}
              className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-lg border text-left transition-colors ${
                selected
                  ? "border-teal-500 bg-teal-50"
                  : unavailable
                    ? "border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed"
                    : "border-gray-200 hover:bg-gray-50"
              }`}
            >
              <div>
                <div className="text-sm font-medium text-gray-900">{driver.driver_name ?? driver.driver_id}</div>
                <div className="text-xs text-gray-500 mt-0.5">{subtitleParts.join(" · ")}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {driver.rating != null && (
                  <span className="flex items-center gap-1 px-2 py-1 rounded-full bg-amber-50 text-amber-600 text-xs font-medium">
                    <IconStar />
                    {driver.rating}
                  </span>
                )}
                <span className={`px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
                  driver.is_on_trip ? "bg-amber-50 text-amber-700" : statusBadgeStyle(driver.status)
                }`}>
                  {driver.is_on_trip ? "On Trip" : (driver.status ?? "Available")}
                </span>
                {driver.license_expiring_soon != null && (
                  <span
                    className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
                      driver.license_expiring_soon ? "bg-red-50 text-red-600" : "bg-emerald-50 text-emerald-700"
                    }`}
                  >
                    {driver.license_expiring_soon ? <IconAlertTriangle /> : <IconShield />}
                    License
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface VehicleStepProps {
  vehicles: VehicleRosterItem[];
  isLoading: boolean;
  selectedVehicleId: string;
  onSelectVehicle: (id: string) => void;
}

function VehicleStep({ vehicles, isLoading, selectedVehicleId, onSelectVehicle }: VehicleStepProps) {
  return (
    <div>
      <label className="block text-sm font-semibold text-gray-900 mb-2">Assign vehicle</label>
      {isLoading && <p className="text-sm text-gray-400">Loading vehicles…</p>}
      {!isLoading && vehicles.length === 0 && <p className="text-sm text-gray-400">No vehicles found.</p>}
      <div className="space-y-2">
        {vehicles.map((vehicle) => {
          const selected = vehicle.vehicle_id === selectedVehicleId;
          const unavailable = vehicle.is_on_trip;
          const subtitleParts = [
            [vehicle.make, vehicle.model].filter(Boolean).join(" "),
            vehicle.load_capacity_kg != null ? `${vehicle.load_capacity_kg.toLocaleString()} kg capacity` : null,
            vehicle.fuel_type,
          ].filter((part) => Boolean(part && part.trim()));

          return (
            <button
              key={vehicle.vehicle_id}
              type="button"
              onClick={() => !unavailable && onSelectVehicle(vehicle.vehicle_id)}
              disabled={unavailable}
              className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-lg border text-left transition-colors ${
                selected
                  ? "border-teal-500 bg-teal-50"
                  : unavailable
                    ? "border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed"
                    : "border-gray-200 hover:bg-gray-50"
              }`}
            >
              <div>
                <div className="text-sm font-medium text-gray-900">
                  {vehicle.vehicle_id} · {vehicle.vehicle_type ?? "—"}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{subtitleParts.join(" · ")}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {vehicle.is_on_trip && (
                  <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium whitespace-nowrap">
                    In Use
                  </span>
                )}
                {vehicle.avg_kmpl_rated != null && (
                  <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-sky-50 text-sky-700 text-xs font-medium whitespace-nowrap">
                    <IconFuel />
                    {vehicle.avg_kmpl_rated} km/l
                  </span>
                )}
                {vehicle.service_due_soon && (
                  <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium whitespace-nowrap">
                    Service due soon
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface LoadStepProps {
  loadWeightKg: string;
  onWeightChange: (value: string) => void;
  loadDescription: string;
  onDescriptionChange: (value: string) => void;
  loadValue: string;
  onValueChange: (value: string) => void;
}

function LoadStep({
  loadWeightKg,
  onWeightChange,
  loadDescription,
  onDescriptionChange,
  loadValue,
  onValueChange,
}: LoadStepProps) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm text-gray-600 mb-1">Load weight (kg)</label>
        <input
          type="number"
          min={0}
          value={loadWeightKg}
          onChange={(e) => onWeightChange(e.target.value)}
          placeholder="e.g. 18000"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
        />
      </div>
      <div>
        <label className="block text-sm text-gray-600 mb-1">Load description</label>
        <input
          type="text"
          value={loadDescription}
          onChange={(e) => onDescriptionChange(e.target.value)}
          placeholder="e.g. Palletized general cargo"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
        />
      </div>
      <div>
        <label className="block text-sm text-gray-600 mb-1">Load value (₹)</label>
        <input
          type="number"
          min={0}
          value={loadValue}
          onChange={(e) => onValueChange(e.target.value)}
          placeholder="e.g. 250000"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
        />
      </div>
    </div>
  );
}

interface ReviewStepProps {
  route: Route;
  driver: DriverRosterItem;
  vehicle: VehicleRosterItem;
  loadWeightKg: string;
  loadDescription: string;
  distanceKm: number;
  estCost: number;
  pickupDateTime: string;
  onPickupDateTimeChange: (value: string) => void;
}

function ReviewStep({
  route,
  driver,
  vehicle,
  loadWeightKg,
  loadDescription,
  distanceKm,
  estCost,
  pickupDateTime,
  onPickupDateTimeChange,
}: ReviewStepProps) {
  const { origin, destination, stopCount } = routeEndpoints(route);

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm text-gray-600 mb-1">Pickup time</label>
        <input
          type="datetime-local"
          value={pickupDateTime}
          onChange={(e) => onPickupDateTimeChange(e.target.value)}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
        />
      </div>

      <div className="border border-gray-200 rounded-xl p-4 grid grid-cols-4 gap-y-3 gap-x-2 text-sm">
        <div className="text-gray-500">Route</div>
        <div className="font-medium text-gray-900">
          {origin} → {destination} ({stopCount} stops)
        </div>
        <div className="text-gray-500 text-right">Driver</div>
        <div className="font-medium text-gray-900 text-right">
          {driver.driver_name ?? driver.driver_id}
          {driver.rating != null ? ` (${driver.rating}★)` : ""}
        </div>

        <div className="text-gray-500">Vehicle</div>
        <div className="font-medium text-gray-900">
          {vehicle.vehicle_id} · {vehicle.vehicle_type ?? "—"}
        </div>
        <div className="text-gray-500 text-right">Load</div>
        <div className="font-medium text-gray-900 text-right">
          {loadWeightKg ? `${Number(loadWeightKg).toLocaleString()} kg` : "—"}
          {loadDescription ? ` · ${loadDescription}` : ""}
        </div>

        <div className="text-gray-500">Distance</div>
        <div className="font-medium text-gray-900">{Math.round(distanceKm)} km</div>
        <div className="text-gray-500 text-right">Est. cost</div>
        <div className="font-medium text-gray-900 text-right">₹{Math.round(estCost).toLocaleString()}</div>
      </div>
    </div>
  );
}
