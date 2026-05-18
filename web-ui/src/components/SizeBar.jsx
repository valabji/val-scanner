export default function SizeBar({ bytes, rootBytes }) {
  const pct = rootBytes > 0 ? Math.min(100, (bytes / rootBytes) * 100) : 0;
  return (
    <div className="h-1.5 w-24 rounded bg-accent/20 inline-block align-middle">
      <div className="h-full rounded bg-accent" style={{ width: `${pct}%` }} />
    </div>
  );
}
