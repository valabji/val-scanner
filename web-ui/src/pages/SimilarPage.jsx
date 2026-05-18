import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { listSimilar } from '../api/folders';
import { useApp } from '../AppContext';
import ScoreBadge from '../components/ScoreBadge';
import Spinner from '../components/Spinner';

function FolderPairCard({ pair, depth }) {
  const [open, setOpen] = useState(false);
  const hasChildren = pair.children && pair.children.length > 0;

  return (
    <div
      className={`border-l-2 border-panel pl-3 ${depth > 0 ? 'ml-4 mt-1' : 'mt-2 bg-panel/30 rounded p-2'}`}
    >
      <div
        className="flex items-center gap-3 cursor-pointer"
        onClick={() => hasChildren && setOpen(!open)}
      >
        <ScoreBadge score={pair.score} label={pair.label} />
        <div className="flex-1 min-w-0 grid grid-cols-2 gap-2">
          <span className="font-mono text-xs truncate" title={pair.folder_a}>{pair.folder_a}</span>
          <span className="font-mono text-xs truncate" title={pair.folder_b}>{pair.folder_b}</span>
        </div>
        <span className="text-muted text-xs whitespace-nowrap">
          {pair.files_a} vs {pair.files_b} files
        </span>
        {hasChildren && <span className="text-muted">{open ? '▾' : '▸'}</span>}
      </div>
      {open && hasChildren && (
        <div className="mt-1">
          {pair.children.map((c, i) => (
            <FolderPairCard key={`${c.folder_a}|${c.folder_b}|${i}`} pair={c} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function SimilarPage() {
  const { activeScanId } = useApp();

  const { data, isLoading } = useQuery({
    queryKey: ['similar', activeScanId],
    queryFn: () => listSimilar(activeScanId),
    enabled: !!activeScanId,
    staleTime: Infinity,
  });

  if (!activeScanId) return <div className="p-4 text-muted">Pick a scan on the Scans tab first.</div>;
  if (isLoading) {
    return (
      <div className="p-4 flex items-center gap-2 text-muted">
        <Spinner /> Analysing folder similarity…
      </div>
    );
  }
  if (!data || data.length === 0) {
    return <div className="p-4 text-muted">No similar folders found in this scan.</div>;
  }

  return (
    <div className="p-4">
      {data.map((p, i) => (
        <FolderPairCard key={`${p.folder_a}|${p.folder_b}|${i}`} pair={p} depth={0} />
      ))}
    </div>
  );
}
