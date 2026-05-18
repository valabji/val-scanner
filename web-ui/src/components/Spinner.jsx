export default function Spinner({ size = 16 }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-2 border-muted border-t-accent"
      style={{ width: size, height: size }}
      aria-label="loading"
    />
  );
}
