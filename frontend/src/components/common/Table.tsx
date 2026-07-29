import { ReactNode } from "react";

export interface TableColumn<T> {
  header: string;
  render: (row: T) => ReactNode;
}

interface TableProps<T> {
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
}

export function Table<T>({ columns, rows, rowKey, onRowClick }: TableProps<T>) {
  return (
    <table className="min-w-full divide-y divide-gray-200">
      <thead>
        <tr>
          {columns.map((col) => (
            <th key={col.header} className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase">
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={onRowClick ? "cursor-pointer hover:bg-gray-50" : ""}
          >
            {columns.map((col) => (
              <td key={col.header} className="px-4 py-2 text-sm text-gray-700">
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
