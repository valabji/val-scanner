import { useCallback, useState } from 'react';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';

import { listScans, deleteScan, cancelScan } from '../api/scans';
import { csvUrl, jsonUrl } from '../api/exportApi';
import { useScanProgress } from '../hooks/useScanProgress';
import { useApp } from '../AppContext';
import ScanProgressBar from '../components/ScanProgressBar';

function NewScanForm({ disabled, onSubmit }) {
  const [root, setRoot] = useState('');
  const [label, setLabel] = useState('');
  const [noHash, setNoHash] = useState(false);

  const submit = (e) => {
    e.preventDefault();
    if (!root.trim()) return;
    onSubmit({ root: root.trim(), label: label.trim(), no_hash: noHash });
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 mb-4">
      <div className="flex-1 min-w-[300px]">
        <label className="block text-xs text-muted mb-1">Root path</label>
        <input
          className="w-full bg-panel rounded px-2 py-1 text-sm font-mono"
          value={root}
          onChange={(e) => setRoot(e.target.value)}
          placeholder="/Users/me/Pictures"
          disabled={disabled}
          required
        />
      </div>
      <div>
        <label className="block text-xs text-muted mb-1">Label</label>
        <input
          className="bg-panel rounded px-2 py-1 text-sm"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="(optional)"
          disabled={disabled}
        />
      </div>
      <label className="text-sm flex items-center gap-1">
        <input type="checkbox" checked={noHash} onChange={(e) => setNoHash(e.target.checked)} disabled={disabled} />
        no-hash
      </label>
      <button
        type="submit"
        disabled={disabled}
        className="px-3 py-1 bg-accent rounded text-sm disabled:opacity-50"
      >
        Start scan
      </button>
    </form>
  );
}

export default function ScansPage() {
  const qc = useQueryClient();
  const { activeScanId, setActiveScanId } = useApp();

  const [progress, setProgress] = useState({ status: 'idle', scanned: 0, path: '' });
  const [runningId, setRunningId] = useState(null);

  const { data: scans = [], isLoading } = useQuery({ queryKey: ['scans'], queryFn: listScans });

  const onProgress = useCallback((d) => {
    setProgress((p) => ({ ...p, status: 'running', scanned: d.scanned ?? p.scanned, path: d.path ?? p.path }));
  }, []);
  const onDone = useCallback((d) => {
    if (d.error)        setProgress({ status: 'error', scanned: 0, path: '' });
    else if (d.cancelled) setProgress((p) => ({ ...p, status: 'cancelled' }));
    else                setProgress((p) => ({ ...p, status: 'done' }));
    setRunningId(null);
    qc.invalidateQueries({ queryKey: ['scans'] });
  }, [qc]);

  const { start } = useScanProgress({ onProgress, onDone });

  const handleStart = async (body) => {
    setProgress({ status: 'running', scanned: 0, path: '' });
    try {
      const id = await start(body);
      setRunningId(id);
      setActiveScanId(id);
    } catch (err) {
      if (err.code === 'scan_in_progress') {
        alert('A scan is already running. Wait for it to finish or cancel it.');
      } else if (err.code === 'invalid_root') {
        alert(err.message);
      } else {
        alert(`Failed to start scan: ${err.message}`);
      }
      setProgress({ status: 'idle', scanned: 0, path: '' });
    }
  };

  const handleCancel = async () => {
    if (!runningId) return;
    setProgress((p) => ({ ...p, status: 'cancelling' }));
    try { await cancelScan(runningId); } catch {}
  };

  const delMut = useMutation({
    mutationFn: deleteScan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans'] }),
  });

  return (
    <div className="p-4">
      <NewScanForm disabled={progress.status === 'running' || progress.status === 'cancelling'} onSubmit={handleStart} />
      <ScanProgressBar status={progress.status} scanned={progress.scanned} path={progress.path} onCancel={handleCancel} />

      <div className="mb-2 flex items-center gap-2">
        <a
          href={activeScanId ? csvUrl(activeScanId) : '#'}
          download
          className={`px-3 py-1 text-sm rounded ${activeScanId ? 'bg-panel hover:bg-panel/70' : 'bg-panel/40 text-muted pointer-events-none'}`}
        >Export CSV</a>
        <a
          href={activeScanId ? jsonUrl(activeScanId) : '#'}
          download
          className={`px-3 py-1 text-sm rounded ${activeScanId ? 'bg-panel hover:bg-panel/70' : 'bg-panel/40 text-muted pointer-events-none'}`}
        >Export JSON</a>
      </div>

      {isLoading ? (
        <div className="text-muted text-sm">Loading…</div>
      ) : scans.length === 0 ? (
        <div className="text-muted text-sm">No scans yet. Start one above.</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-1">#</th>
              <th>Label</th>
              <th>Root</th>
              <th className="text-right">Files</th>
              <th>Size</th>
              <th>Date</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {scans.map((s) => (
              <tr
                key={s.id}
                onClick={() => setActiveScanId(s.id)}
                className={`cursor-pointer hover:bg-panel/40 ${activeScanId === s.id ? 'bg-panel border-l-2 border-accent' : ''}`}
              >
                <td className="py-1">{s.id}</td>
                <td>{s.label || <span className="text-muted">—</span>}</td>
                <td className="font-mono text-xs truncate max-w-[300px]" title={s.root}>{s.root}</td>
                <td className="text-right">{s.file_count ?? 0}</td>
                <td>{s.total_human ?? ''}</td>
                <td>{s.scanned_at}</td>
                <td>
                  <button
                    onClick={(e) => { e.stopPropagation(); if (confirm(`Delete scan ${s.id}?`)) delMut.mutate(s.id); }}
                    disabled={s.id === runningId}
                    className="text-rose-300 hover:text-rose-200 disabled:text-muted"
                  >Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
