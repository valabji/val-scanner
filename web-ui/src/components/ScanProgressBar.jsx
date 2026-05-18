import Spinner from './Spinner';

export default function ScanProgressBar({ status, scanned, path, onCancel }) {
  if (status === 'idle') return null;
  const label =
    status === 'running'    ? `Scanning… ${scanned} files`  :
    status === 'cancelling' ? 'Cancelling…'                 :
    status === 'done'       ? `Done — ${scanned} files indexed` :
    status === 'cancelled'  ? 'Cancelled'                   :
    status === 'error'      ? 'Scan failed'                 : '';

  const showCancel = status === 'running';

  return (
    <div className="bg-panel rounded p-3 mb-4 flex items-center gap-3">
      {(status === 'running' || status === 'cancelling') && <Spinner />}
      <div className="flex-1 min-w-0">
        <div className="text-sm">{label}</div>
        {path && status === 'running' && (
          <div className="text-xs text-muted truncate font-mono" title={path}>{path}</div>
        )}
      </div>
      {showCancel && (
        <button
          onClick={onCancel}
          className="px-3 py-1 text-sm rounded bg-rose-500/20 text-rose-300 hover:bg-rose-500/30"
        >
          Cancel
        </button>
      )}
    </div>
  );
}
