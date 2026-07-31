export function riskBadge(probability: number): { label: string; className: string } {
  if (probability >= 0.5) return { label: "High", className: "bg-red-50 text-red-600" };
  if (probability >= 0.25) return { label: "Medium", className: "bg-amber-50 text-amber-600" };
  return { label: "Low", className: "bg-green-50 text-green-600" };
}
