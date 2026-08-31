import { NavLink } from "react-router-dom";
import {
  IconDashboard,
  IconTrips,
  IconVehicle,
  IconDriver,
  IconMaintenance,
  IconReports,
  IconSettings,
} from "./icons";

const navItems = [
  { label: "Dashboard Home", path: "/dashboard", icon: IconDashboard },
  { label: "Live Assignment", path: "/live-ops", icon: IconDashboard },
  { label: "Trips", path: "/trips", icon: IconTrips },
  { label: "Vehicles", path: "/vehicles", icon: IconVehicle },
  { label: "Drivers", path: "/drivers", icon: IconDriver },
  { label: "Maintenance", path: "/maintenance", icon: IconMaintenance },
  { label: "Reports", path: "/reports", icon: IconReports },
  { label: "Settings", path: "/settings", icon: IconSettings },
];

export function Sidebar() {
  return (
    <aside className="w-64 bg-slate-950 text-slate-100 flex flex-col shrink-0 border-r border-slate-800">
      <div className="flex items-center gap-3 px-5 py-5 border-b border-slate-800">
        <div className="w-9 h-9 rounded-lg bg-teal-500 flex items-center justify-center font-bold text-white">
          M
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">Meridian Fleet</div>
          <div className="text-xs text-slate-400">Optimization Suite</div>
        </div>
      </div>

      <div className="px-5 pt-5 pb-2 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
        Operations
      </div>
      <nav className="flex-1 px-3 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-900 hover:text-white"
                }`
              }
            >
              <Icon className="shrink-0" />
              {item.label}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
