import { NavLink } from "react-router-dom";

const navItems = [
  { label: "Trips", path: "/trips" },
];

export function Sidebar() {
  return (
    <aside className="w-56 bg-gray-900 text-gray-100 flex flex-col shrink-0">
      <div className="px-4 py-4 text-lg font-semibold border-b border-gray-800">Fleet Optimization</div>
      <nav className="flex-1 px-2 py-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `block px-3 py-2 rounded-md text-sm ${isActive ? "bg-gray-800 text-white" : "text-gray-300 hover:bg-gray-800"}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
