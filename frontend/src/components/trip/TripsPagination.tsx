interface TripsPaginationProps {
  page: number;
  pageSize: number;
  rowCount: number;
  hasNextPage: boolean;
  onPageChange: (page: number) => void;
}

export function TripsPagination({ page, pageSize, rowCount, hasNextPage, onPageChange }: TripsPaginationProps) {
  const rangeStart = rowCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = (page - 1) * pageSize + rowCount;

  return (
    <div className="flex items-center justify-between px-1">
      <span className="text-sm text-gray-500">
        {rowCount > 0 ? `Showing ${rangeStart}–${rangeEnd}` : "No trips"}
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="px-3 py-1.5 rounded-lg border border-gray-200 bg-white text-sm text-gray-700 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
        >
          Previous
        </button>
        <span className="text-sm text-gray-600 px-2">Page {page}</span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={!hasNextPage}
          className="px-3 py-1.5 rounded-lg border border-gray-200 bg-white text-sm text-gray-700 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}
