import type { DelayPrediction } from '@/types/delayPrediction';

interface DelayBadgeProps {
  prediction?: DelayPrediction | null;
  loading?: boolean;
  expectedMinutes?: number;
  compact?: boolean;
}

export function DelayBadge({ prediction, loading, expectedMinutes, compact = false }: DelayBadgeProps) {
  const size = compact ? 'px-1.5 py-0.5 text-[9px]' : 'px-2 py-0.5 text-[10px]';

  if (loading && !prediction) {
    return (
      <span className={`inline-flex items-center gap-1 rounded-full bg-slate-800 text-slate-500 ${size}`}>
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600 animate-pulse" />
        Analyzing…
      </span>
    );
  }

  if (!prediction) {
    return (
      <span className={`inline-flex items-center gap-1 rounded-full bg-slate-800 text-slate-500 ${size}`}>
        No prediction
      </span>
    );
  }

  const prob = prediction.delay_probability;
  const isDelayed = prediction.is_delayed_prediction;
  const pct = Math.round(prob * 100);

  const bg = isDelayed
    ? pct >= 70 ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'
    : 'bg-emerald-500/20 text-emerald-400';

  const icon = isDelayed ? (pct >= 70 ? '🔴' : '🟡') : '🟢';

  return (
    <span className={`inline-flex items-center gap-1 rounded-full font-medium ${bg} ${size}`}>
      <span>{icon}</span>
      <span>{isDelayed ? 'Delayed' : 'On time'}</span>
      {!compact && <span className="opacity-60">{pct}%</span>}
      {expectedMinutes != null && expectedMinutes > 0 && !compact && (
        <span className="opacity-60">+{expectedMinutes.toFixed(0)}m</span>
      )}
    </span>
  );
}