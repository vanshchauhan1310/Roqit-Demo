import { useState } from "react";
import { Trip } from "@/types/trip";
import { RouteIntelligenceTab } from "./RouteIntelligenceTab";
import { VehicleIntelligenceTab } from "./VehicleIntelligenceTab";
import { DriverIntelligenceTab } from "./DriverIntelligenceTab";
import { RealTimeOpsTab } from "./RealTimeOpsTab";
import { ReportingKpiTab } from "./ReportingKpiTab";

type TabKey = "route" | "vehicle" | "driver" | "realtime" | "reporting";

const tabs: { key: TabKey; label: string }[] = [
  { key: "route", label: "Route Intelligence" },
  { key: "vehicle", label: "Vehicle Intelligence" },
  { key: "driver", label: "Driver Intelligence" },
  { key: "realtime", label: "Real-Time Operations" },
  { key: "reporting", label: "Reporting & KPI" },
];

interface TripDetailTabsProps {
  trip: Trip;
}

export function TripDetailTabs({ trip }: TripDetailTabsProps) {
  const [active, setActive] = useState<TabKey>("route");

  return (
    <div>
      <div className="flex gap-2 border-b border-gray-200 mb-4">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActive(tab.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
              active === tab.key
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {active === "route" && <RouteIntelligenceTab trip={trip} />}
      {active === "vehicle" && <VehicleIntelligenceTab trip={trip} />}
      {active === "driver" && <DriverIntelligenceTab trip={trip} />}
      {active === "realtime" && <RealTimeOpsTab trip={trip} />}
      {active === "reporting" && <ReportingKpiTab trip={trip} />}
    </div>
  );
}
