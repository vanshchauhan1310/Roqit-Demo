import { useMemo, useState } from "react";
import { useFleet } from "@/hooks/useFleet";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { Driver } from "@/api/fleet";

function driverMatches(d: Driver, search: string, status: string): boolean {
  if (status && d.status !== status) return false;
  if (search) {
    const q = search.toLowerCase();
    const haystack = [d.driver_id, d.driver_name, d.license_type, d.base_location]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(q)) return false;
  }
  return true;
}

export function DriversPage() {
  const { drivers, loading } = useFleet();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const debouncedSearch = useDebouncedValue(search);

  const filteredDrivers = useMemo(() => {
    if (!debouncedSearch && !status) return drivers;
    return drivers.filter((d) => driverMatches(d, debouncedSearch, status));
  }, [drivers, debouncedSearch, status]);

  const statusOptions = useMemo(
    () => Array.from(new Set(drivers.map((d) => d.status).filter(Boolean))).sort() as string[],
    [drivers],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Drivers</h1>
        <p className="text-sm text-gray-500 mt-1">Driver roster — {drivers.length} drivers total</p>
      </div>
      <div className="flex flex-wrap items-center gap-3 bg-white rounded-xl border border-gray-200 p-4">
        <input
          type="text"
          placeholder="Search drivers..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 w-64"
        />
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500">
          <option value="">All Statuses</option>
          {statusOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="text-sm text-gray-500 ml-auto">Showing {filteredDrivers.length} of {drivers.length}</span>
      </div>
      {loading && <p className="text-sm text-gray-500">Loading drivers...</p>}
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-gray-100">
              {["Driver ID", "Name", "License", "Experience", "Rating", "Base", "Status"].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filteredDrivers.map((d) => (
              <tr key={d.driver_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm font-mono text-gray-900 whitespace-nowrap">{d.driver_id}</td>
                <td className="px-4 py-3 text-sm font-medium text-gray-900 whitespace-nowrap">{d.driver_name}</td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{d.license_type ?? "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{d.experience_years ? `${d.experience_years} yrs` : "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                  {d.rating ? <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 text-xs font-medium">★ {d.rating.toFixed(1)}</span> : "—"}
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{d.base_location ?? "—"}</td>
                <td className="px-4 py-3 text-sm whitespace-nowrap">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${d.status === "active" ? "bg-emerald-50 text-emerald-700" : d.status === "available" ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-600"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${d.status === "active" ? "bg-emerald-500" : d.status === "available" ? "bg-blue-500" : "bg-gray-400"}`} />
                    {d.status ?? "—"}
                  </span>
                </td>
              </tr>
            ))}
            {filteredDrivers.length === 0 && !loading && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">No drivers match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
