import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { listFolders } from '../api/folders';
import { useApp } from '../AppContext';
import SizeBar from '../components/SizeBar';

function FolderNode({ node, rootSize, depth }) {
  const [open, setOpen] = useState(depth < 1);
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div>
      <div
        className="flex items-center gap-2 py-1 hover:bg-panel/40 cursor-pointer"
        style={{ paddingLeft: depth * 16 }}
        onClick={() => hasChildren && setOpen(!open)}
      >
        <span className="w-4 text-muted">{hasChildren ? (open ? '▾' : '▸') : ' '}</span>
        <span className="flex-1 truncate" title={node.path}>{node.name || node.path}</span>
        <SizeBar bytes={node.total_size} rootBytes={rootSize} />
        <span className="text-muted text-xs w-20 text-right">{node.size_human}</span>
        <span className="text-muted text-xs w-16 text-right">{node.file_count} files</span>
      </div>
      {open && hasChildren && node.children.map((c) => (
        <FolderNode key={c.path} node={c} rootSize={rootSize} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function FoldersPage() {
  const { activeScanId } = useApp();

  const { data, isLoading } = useQuery({
    queryKey: ['folders', activeScanId],
    queryFn: () => listFolders(activeScanId),
    enabled: !!activeScanId,
  });

  if (!activeScanId) return <div className="p-4 text-muted">Pick a scan on the Scans tab first.</div>;
  if (isLoading) return <div className="p-4 text-muted">Loading…</div>;
  if (!data) return <div className="p-4 text-muted">No folders in this scan.</div>;

  return (
    <div className="p-4">
      <FolderNode node={data} rootSize={data.total_size} depth={0} />
    </div>
  );
}
