import { useMemo, useState } from "react";
import { useFleet } from "@/hooks/useFleet";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { Vehicle } from "@/api/fleet";

const typeStyles: Record<string, string> = {
  "Mini Truck": "bg-blue-50 text-blue-700",
  Truck: "bg-emerald-50 text-emerald-700",
  "Container Truck": "bg-purple-50 text-purple-700",
  "Refrigerated Truck": "bg-cyan-50 text-cyan-700",
  Trailer: "bg-orange-50 text-orange-700",
};

function vehicleMatches(v: Vehicle, search: string, type: string, status: string): boolean {
  if (type && v.vehicle_type !== type) return false;
  if (status && v.status !== status) return false;
  if (search) {
    const q = search.toLowerCase();
    const haystack = [v.vehicle_id, v.vehicle_type, v.make, v.model, v.fuel_type, v.base_location]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(q)) return false;
  }

export function VehiclesPage() {
  const { vehicles, loading } = useFleet();
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const debouncedSearch = useDebouncedValue(search);

  const filteredVehicles = useMemo(() => {
    if (!debouncedSearch && !type && !status) return vehicles;
    return vehicles.filter((v) => vehicleMatches(v, debouncedSearch, type, status));
  }, [vehicles, debouncedSearch, type, status]);

  const typeOptions = useMemo(
    () => Array.from(new Set(vehicles.map((v) => v.vehicle_type).filter(Boolean))).sort(),
    [vehicles],
  );

  const statusOptions = useMemo(
    () => Array.from(new Set(vehicles.map((v) => v.status).filter(Boolean))).sort(),
    [vehicles],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Vehicles</h1>
          <p className="text-sm text-gray-500 mt-1">Fleet roster — {vehicles.length} vehicles total</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 bg-white rounded-xl border border-gray-200 p-4">
        <input
          type="text"
          placeholder="Search vehicles..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 w-64"
        />
        <select value={type} onChange={(e) => setType(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500">
          <option value="">All Types</option>
          {typeOptions.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500">
          <option value="">All Statuses</option>
          {statusOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="text-sm text-gray-500 ml-auto">Showing {filteredVehicles.length} of {vehicles.length}</span>
      </div>
      {loading && <p className="text-sm text-gray-500">Loading vehicles...</p>}
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-gray-100">
              {["Vehicle ID", "Type", "Make & Model", "Year", "Fuel", "Capacity", "Status"].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filteredVehicles.map((v) => (
              <tr key={v.vehicle_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm font-mono text-gray-900 whitespace-nowrap">{v.vehicle_id}</td>
                <td className="px-4 py-3 text-sm whitespace-nowrap">
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${typeStyles[v.vehicle_type ?? ""] ?? "bg-gray-100 text-gray-600"}`}>
                    {v.vehicle_type ?? "—"}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                  <div className="font-medium">{v.make ?? "—"}</div>
                  <div className="text-xs text-gray-400">{v.model ?? ""}</div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{v.year ?? "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap capitalize">{v.fuel_type ?? "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                  {v.load_capacity_kg ? `${v.load_capacity_kg.toLocaleString()} kg` : "—"}
                </td>
                <td className="px-4 py-3 text-sm whitespace-nowrap">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${v.status === "active" ? "bg-emerald-50 text-emerald-700" : v.status === "available" ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-600"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${v.status === "active" ? "bg-emerald-500" : v.status === "available" ? "bg-blue-500" : "bg-gray-400"}`} />
                    {v.status ?? "—"}
                  </span>
                </td>
              </tr>
            ))}
            {filteredVehicles.length === 0 && !loading && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">No vehicles match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

  return true;
}
