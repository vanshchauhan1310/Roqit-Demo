/** Stable per-route colors — same route always gets the same color. */

export const ROUTE_COLORS = [
  "#0d9488", // teal
  "#2563eb", // blue
  "#7c3aed", // violet
  "#db2777", // pink
  "#ea580c", // orange
  "#16a34a", // green
  "#d97706", // amber
  "#0284c7", // sky
] as const;

/** Deterministic hash so a route keeps its color across refreshes. */
export function colorForRouteId(routeId: string): string {
  let h = 0;
  for (let i = 0; i < routeId.length; i++) {
    h = (h * 31 + routeId.charCodeAt(i)) >>> 0;
  }
  return ROUTE_COLORS[h % ROUTE_COLORS.length];
}