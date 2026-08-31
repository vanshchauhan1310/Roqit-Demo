import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "@/components/common/Sidebar";
import { Topbar } from "@/components/common/Topbar";
import { ToastProvider } from "@/components/common/Toast";
import { TripsPage } from "@/pages/TripsPage";
import { TripDetailPage } from "@/pages/TripDetailPage";
import { RouteDetailPage } from "@/pages/RouteDetailPage";
import { LiveOpsPage } from "@/pages/LiveOpsPage";

export default function App() {
  return (
    <ToastProvider>
      <div className="flex h-screen bg-gray-50">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Topbar />
          <main className="flex-1 overflow-y-auto p-6">
            <Routes>
              <Route path="/" element={<Navigate to="/trips" replace />} />
              <Route path="/live-ops" element={<LiveOpsPage />} />
              <Route path="/trips" element={<TripsPage />} />
              <Route path="/trips/:tripId" element={<TripDetailPage />} />
              <Route path="/routes/:routeId" element={<RouteDetailPage />} />
            </Routes>
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
