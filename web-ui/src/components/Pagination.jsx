export default function Pagination({ page, pageSize, total, onChange, onPageSizeChange }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <div className="flex items-center gap-3 text-sm text-muted mt-2">
      <span>{from}–{to} of {total}</span>
      <button
        className="px-2 py-0.5 bg-panel rounded disabled:opacity-40"
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
      >Prev</button>
      <span>Page {page} / {totalPages}</span>
      <button
        className="px-2 py-0.5 bg-panel rounded disabled:opacity-40"
        onClick={() => onChange(page + 1)}
        disabled={page >= totalPages}
      >Next</button>
      <select
        value={pageSize}
        onChange={(e) => onPageSizeChange(Number(e.target.value))}
        className="bg-panel rounded px-1 py-0.5"
      >
        <option value={25}>25</option>
        <option value={100}>100</option>
        <option value={500}>500</option>
      </select>
    </div>
  );
}
