import { useEffect, useRef } from 'react';

import { useApp } from '../AppContext';
import { thumbnailUrl, sampleUrl, revealFile } from '../api/files';
import TagChip from '../components/TagChip';

function snakeToTitle(s) {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderMetaValue(value, depth = 0) {
  if (value === null || value === undefined || value === '') return null;
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    if (value.length <= 3) return value.join(', ');
    return (
      <ul className="list-disc pl-4 text-xs">
        {value.map((v, i) => <li key={i}>{String(v)}</li>)}
      </ul>
    );
  }
  if (typeof value === 'object') {
    return (
      <dl className="pl-2">
        {Object.entries(value).map(([k, v]) => {
          const rendered = renderMetaValue(v, depth + 1);
          if (rendered === null) return null;
          return (
            <div key={k} className="flex gap-2 text-xs">
              <dt className="text-muted w-24">{snakeToTitle(k)}</dt>
              <dd className="flex-1 break-all">{rendered}</dd>
            </div>
          );
        })}
      </dl>
    );
  }
  return String(value);
}

export default function DetailPanel() {
  const { selectedFile, setSelectedFile } = useApp();
  const closeBtnRef = useRef(null);
  const lastActiveRef = useRef(null);

  const isOpen = !!selectedFile;

  // Save / restore focus, bind ESC, lock background scroll while open.
  useEffect(() => {
    if (!isOpen) return;
    lastActiveRef.current = document.activeElement;
    closeBtnRef.current?.focus();
    const onKey = (e) => { if (e.key === 'Escape') setSelectedFile(null); };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      if (lastActiveRef.current && typeof lastActiveRef.current.focus === 'function') {
        lastActiveRef.current.focus();
      }
    };
  }, [isOpen, setSelectedFile]);

  const file = selectedFile;
  const extraMeta = (() => {
    if (!file || !file.extra_meta) return null;
    if (typeof file.extra_meta === 'string') {
      try { return JSON.parse(file.extra_meta); } catch { return null; }
    }
    return file.extra_meta;
  })();

  const isAudioOrVideo = file && (file.category === 'audio' || file.category === 'video');

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-label="File details"
      aria-hidden={!isOpen}
      className={`fixed right-0 top-0 h-full w-80 max-w-full bg-panel shadow-2xl z-40
                  transition-transform duration-200
                  ${isOpen ? 'translate-x-0' : 'translate-x-full pointer-events-none'}`}
    >
      {file && (
        <div className="flex flex-col h-full overflow-y-auto">
          <div className="flex items-start p-3 border-b border-bg">
            <h2 className="flex-1 text-lg font-semibold truncate" title={file.name}>{file.name}</h2>
            <button
              ref={closeBtnRef}
              onClick={() => setSelectedFile(null)}
              aria-label="Close details"
              className="text-muted hover:text-text px-2"
            >×</button>
          </div>

          <div className="p-3">
            <div className="h-48 bg-bg rounded flex items-center justify-center overflow-hidden mb-3">
              {file.has_thumbnail ? (
                <img
                  src={thumbnailUrl(file.id)}
                  alt=""
                  className="object-contain w-full h-full"
                  onError={(e) => { e.currentTarget.style.display = 'none'; }}
                />
              ) : (
                <span className="text-muted text-4xl">{file.category[0].toUpperCase()}</span>
              )}
            </div>

            <div className="text-xs font-mono text-muted break-all mb-3" title={file.path}>{file.path}</div>

            <dl className="text-sm mb-3 space-y-1">
              <div className="flex"><dt className="w-24 text-muted">Size</dt><dd>{file.size_human}</dd></div>
              <div className="flex"><dt className="w-24 text-muted">Category</dt><dd>{file.category}</dd></div>
              {file.modified_at && (
                <div className="flex"><dt className="w-24 text-muted">Modified</dt><dd>{file.modified_at}</dd></div>
              )}
            </dl>

            {file.tags && file.tags.length > 0 && (
              <div className="mb-3">
                <div className="text-xs text-muted mb-1">Tags</div>
                <div className="flex flex-wrap gap-1">
                  {file.tags.map((t) => <TagChip key={t} tag={t} />)}
                </div>
              </div>
            )}

            {isAudioOrVideo && (
              <div className="mb-3">
                {file.category === 'audio' ? (
                  <audio controls src={sampleUrl(file.id)} className="w-full"
                         onError={(e) => { e.currentTarget.style.display = 'none'; }} />
                ) : (
                  <video controls src={sampleUrl(file.id)} className="w-full"
                         onError={(e) => { e.currentTarget.style.display = 'none'; }} />
                )}
              </div>
            )}

            {extraMeta && Object.keys(extraMeta).length > 0 && (
              <details className="mb-3">
                <summary className="cursor-pointer text-sm text-muted">Extra metadata</summary>
                <div className="mt-2">{renderMetaValue(extraMeta)}</div>
              </details>
            )}

            <button
              onClick={async () => {
                try { await revealFile(file.id); }
                catch (err) { alert(`Reveal failed: ${err.message}`); }
              }}
              className="px-3 py-1 text-sm rounded bg-accent/30 hover:bg-accent/50"
            >Open in Finder/Explorer</button>
          </div>
        </div>
      )}
    </aside>
  );
}
