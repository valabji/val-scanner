export default function ScoreBadge({ score, label }) {
  const cls =
    score >= 0.90 ? 'bg-emerald-500/20 text-emerald-300' :
    score >= 0.70 ? 'bg-amber-500/20 text-amber-300' :
                    'bg-rose-500/20 text-rose-300';
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-mono ${cls}`} title={label}>
      {score.toFixed(2)}
    </span>
  );
}
