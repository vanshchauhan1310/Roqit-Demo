import { IconBell, IconPanel, IconSearch } from "./icons";

export function Topbar() {
  return (
    <header className="flex items-center gap-4 px-6 py-3 border-b border-gray-200 bg-white">
      <button className="text-gray-500 hover:text-gray-700">
        <IconPanel />
      </button>

      <div className="flex-1 max-w-xl relative">
        <IconSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          placeholder="Search trips, drivers, vehicles..."
          className="w-full pl-10 pr-4 py-2 rounded-full border border-gray-200 bg-gray-50 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/40"
        />
      </div>

      <div className="flex items-center gap-4 text-sm text-gray-600 ml-auto">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-500" /> 18 Active
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-amber-500" /> 3 In Maintenance
        </span>
        <span className="text-gray-300">|</span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-gray-400" /> 4 Idle
        </span>
      </div>

      <button className="relative text-gray-500 hover:text-gray-700">
        <IconBell />
        <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500 text-white text-[10px] flex items-center justify-center">
          5
        </span>
      </button>

      <div className="w-9 h-9 rounded-full bg-slate-800 text-white text-sm flex items-center justify-center font-medium">
        JD
      </div>
    </header>
  );
}
