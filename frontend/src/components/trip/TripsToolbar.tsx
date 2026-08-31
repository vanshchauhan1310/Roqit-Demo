import { useState } from "react";
import { IconCalendar, IconGrid, IconMap, IconSearch, IconTable, IconInbox } from "@/components/common/icons";

type ViewMode = "table" | "map" | "columns";

interface TabConfig {
  key: "incoming" | "assignment" | "routes";
  label: string;
  icon: typeof IconInbox;
  count: number;
}

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
  activeTab: "incoming" | "assignment" | "routes";
  onTabChange: (tab: "incoming" | "assignment" | "routes") => void;
  tabs: TabConfig[];
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
  activeTab,
  onTabChange,
  tabs,
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

      {/* View tabs: Incoming / Assignment / Routes */}
      <div className="flex items-center gap-1 border border-gray-200 rounded-lg p-1 bg-white">
        {tabs.map(({ key, label, icon: Icon, count }) => (
          <button
            key={key}
            onClick={() => onTabChange(key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              activeTab === key
                ? "bg-teal-50 text-teal-700"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
            }`}
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
            <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
              activeTab === key ? "bg-teal-100 text-teal-700" : "bg-gray-100 text-gray-500"
            }`}>
              {count}
            </span>
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1 border border-gray-200 rounded-lg p-1 bg-white ml-auto">
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
