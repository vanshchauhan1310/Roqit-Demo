import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "@/components/common/Sidebar";
import { TripsPage } from "@/pages/TripsPage";
import { TripDetailPage } from "@/pages/TripDetailPage";

export default function App() {
  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <Routes>
          <Route path="/" element={<Navigate to="/trips" replace />} />
          <Route path="/trips" element={<TripsPage />} />
          <Route path="/trips/:tripId" element={<TripDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
