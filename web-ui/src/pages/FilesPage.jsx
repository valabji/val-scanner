import { useState } from 'react';
import { useQuery, keepPreviousData } from '@tanstack/react-query';

import { listFiles, thumbnailUrl } from '../api/files';
import { useApp } from '../AppContext';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import Pagination from '../components/Pagination';
import FileCard from '../components/FileCard';

const CATEGORIES = ['', 'image', 'audio', 'video', 'document', 'archive', 'code', 'other'];

const CATEGORY_TEXT = {
  image: 'text-rose-400', audio: 'text-sky-400', video: 'text-violet-400',
  document: 'text-amber-400', archive: 'text-orange-400', code: 'text-emerald-400',
  other: 'text-muted',
};

export default function FilesPage() {
  const { activeScanId, setSelectedFile, selectedFile } = useApp();

  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [view, setView] = useState('table');

  const debouncedSearch = useDebouncedValue(search, 300);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['files', activeScanId, debouncedSearch, category, page, pageSize],
    queryFn: () => listFiles({
      scan_id: activeScanId, search: debouncedSearch, category, page, page_size: pageSize,
    }),
    placeholderData: keepPreviousData,
    enabled: !!activeScanId,
  });

  if (!activeScanId) {
    return <div className="p-4 text-muted">Pick a scan on the Scans tab first.</div>;
  }
  if (isError) {
    return <div className="p-4 text-rose-300">Error: {error?.message ?? 'unknown'}</div>;
  }

  const items = data?.items ?? [];

  return (
    <div className="p-4">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input
          className="bg-panel rounded px-2 py-1 text-sm flex-1 min-w-[200px]"
          placeholder="Search… (FTS5)"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        />
        <select
          className="bg-panel rounded px-2 py-1 text-sm"
          value={category}
          onChange={(e) => { setCategory(e.target.value); setPage(1); }}
        >
          {CATEGORIES.map((c) => <option key={c} value={c}>{c || 'all'}</option>)}
        </select>
        <button
          onClick={() => setView(view === 'table' ? 'grid' : 'table')}
          className="bg-panel rounded px-2 py-1 text-sm"
        >{view === 'table' ? 'Grid' : 'Table'}</button>
      </div>

      {isLoading && <div className="text-muted text-sm">Loading…</div>}

      {!isLoading && items.length === 0 && (
        <div className="text-muted text-sm">No files match these filters.</div>
      )}

      {view === 'table' && items.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-1 w-10"></th>
              <th>Name</th>
              <th>Category</th>
              <th className="text-right">Size</th>
              <th>Tags</th>
              <th>Path</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <tr
                key={f.id}
                onClick={() => setSelectedFile(f)}
                className={`cursor-pointer hover:bg-panel/40 ${selectedFile?.id === f.id ? 'bg-panel border-l-2 border-accent' : ''}`}
              >
                <td className="py-1">
                  {f.has_thumbnail ? (
                    <img src={thumbnailUrl(f.id)} alt="" width={32} height={32} loading="lazy"
                         className="object-cover rounded"
                         onError={(e) => { e.currentTarget.style.display = 'none'; }} />
                  ) : null}
                </td>
                <td className="truncate max-w-[260px]" title={f.name}>{f.name}</td>
                <td className={CATEGORY_TEXT[f.category] || 'text-muted'}>{f.category}</td>
                <td className="text-right">{f.size_human}</td>
                <td className="text-xs text-muted truncate max-w-[200px]" title={f.tags.join(', ')}>
                  {f.tags.join(', ')}
                </td>
                <td className="font-mono text-xs text-muted truncate max-w-[300px]" title={f.path}>{f.path}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {view === 'grid' && items.length > 0 && (
        <div className="flex flex-wrap">
          {items.map((f) => (
            <FileCard
              key={f.id}
              file={f}
              selected={selectedFile?.id === f.id}
              onClick={() => setSelectedFile(f)}
            />
          ))}
        </div>
      )}

      {data && (
        <Pagination
          page={data.page}
          pageSize={data.page_size}
          total={data.total}
          onChange={setPage}
          onPageSizeChange={(s) => { setPageSize(s); setPage(1); }}
        />
      )}
    </div>
  );
}
