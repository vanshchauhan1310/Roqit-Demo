import { useState } from "react";
import { IconCalendar, IconGrid, IconMap, IconSearch, IconTable } from "@/components/common/icons";

type ViewMode = "table" | "map" | "columns";

interface TripsToolbarProps {
  search: string;
  onSearchChange: (value: string) => void;
  pickupDate: string;
  onPickupDateChange: (value: string) => void;
  status: string;
  onStatusChange: (value: string) => void;
  statusOptions: string[];
  driver: string;
  onDriverChange: (value: string) => void;
  driverOptions: string[];
}

export function TripsToolbar({
  search,
  onSearchChange,
  pickupDate,
  onPickupDateChange,
  status,
  onStatusChange,
  statusOptions,
  driver,
  onDriverChange,
  driverOptions,
}: TripsToolbarProps) {
  const [view, setView] = useState<ViewMode>("table");

  const viewButtons: { key: ViewMode; icon: typeof IconGrid }[] = [
    { key: "table", icon: IconGrid },
    { key: "map", icon: IconMap },
    { key: "columns", icon: IconTable },
  ];

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex-1 min-w-[220px] relative">
        <IconSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search trip, route, driver or vehicle"
          className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/40"
        />
      </div>

      <div className="relative">
        <IconCalendar className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          type="date"
          value={pickupDate}
          onChange={(e) => onPickupDateChange(e.target.value)}
          className="pl-9 pr-3 py-2 rounded-lg border border-gray-200 bg-white text-sm text-gray-700"
        />
      </div>

      <select
        value={status}
        onChange={(e) => onStatusChange(e.target.value)}
        className="px-3 py-2 rounded-lg border border-gray-200 bg-white text-sm text-gray-700"
      >
        <option value="">All statuses</option>
        {statusOptions.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      <select
        value={driver}
        onChange={(e) => onDriverChange(e.target.value)}
        className="px-3 py-2 rounded-lg border border-gray-200 bg-white text-sm text-gray-700"
      >
        <option value="">All drivers</option>
        {driverOptions.map((d) => (
          <option key={d} value={d}>
            {d}
          </option>
        ))}
      </select>

      <div className="flex items-center gap-1 border border-gray-200 rounded-lg p-1 bg-white">
        {viewButtons.map(({ key, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={`p-1.5 rounded-md ${view === key ? "bg-teal-50 text-teal-600" : "text-gray-400 hover:text-gray-600"}`}
          >
            <Icon />
          </button>
        ))}
      </div>
    </div>
  );
}
