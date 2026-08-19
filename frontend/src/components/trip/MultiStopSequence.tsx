import type { StopProgress } from "@/utils/stopProgress";
import { stopProgressBadgeStyle, stopProgressLabel, stopProgressMarkerColor } from "@/utils/stopProgress";

function formatWindow(start: string | null, end: string | null): string {
  const fmt = (iso: string) =>
    new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  if (start && end) return `window ${fmt(start)} – ${fmt(end)}`;
  if (start) return `window from ${fmt(start)}`;
  if (end) return `window until ${fmt(end)}`;
  return "no window set";
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface MultiStopSequenceProps {
  stopProgress: StopProgress[];
}

export function MultiStopSequence({ stopProgress }: MultiStopSequenceProps) {
  return (
    <div className="space-y-0">
      {stopProgress.map(({ stop, arrivedAt, status }, index) => {
        const color = stopProgressMarkerColor[status];
        const filled = status !== "pending";

        return (
          <div key={stop.stop_id} className="flex gap-3 py-3 border-b border-gray-100 last:border-b-0">
            <span
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0"
              style={
                filled
                  ? { backgroundColor: color, color: "#fff" }
                  : { backgroundColor: "#fff", color, border: `2px solid ${color}` }
              }
            >
              {index + 1}
            </span>

            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-gray-900">{stop.address?.split(",")[0] ?? `Stop ${index + 1}`}</div>
              <div className="text-xs text-gray-500 mt-0.5">{stop.address ?? "—"}</div>
              <div className="text-xs text-gray-400 mt-0.5">
                {capitalize(stop.stop_type)} · {formatWindow(stop.window_start, stop.window_end)}
                {stop.eta && ` · ETA ${formatTime(new Date(stop.eta))}`}
                {arrivedAt && ` · arrived ${formatTime(arrivedAt)}`}
              </div>
            </div>

            <span
              className={`shrink-0 self-start px-3 py-1 rounded-full text-xs font-medium whitespace-nowrap ${stopProgressBadgeStyle[status]}`}
            >
              {stopProgressLabel[status]}
            </span>
          </div>
        );
      })}
    </div>
  );
}
