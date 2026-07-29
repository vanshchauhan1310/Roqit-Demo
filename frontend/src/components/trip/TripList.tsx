import { useNavigate } from "react-router-dom";
import { Table, TableColumn } from "@/components/common/Table";
import { Trip } from "@/types/trip";
import { formatDateTime } from "@/utils/format";

interface TripListProps {
  trips: Trip[];
}

export function TripList({ trips }: TripListProps) {
  const navigate = useNavigate();

  const columns: TableColumn<Trip>[] = [
    { header: "Trip ID", render: (t) => t.trip_id.slice(0, 8) },
    { header: "Origin", render: (t) => t.origin ?? "—" },
    { header: "Destination", render: (t) => t.destination ?? "—" },
    { header: "Status", render: (t) => t.status },
    { header: "Scheduled Start", render: (t) => formatDateTime(t.scheduled_start) },
  ];

  return (
    <Table
      columns={columns}
      rows={trips}
      rowKey={(t) => t.trip_id}
      onRowClick={(t) => navigate(`/trips/${t.trip_id}`)}
    />
  );
}
