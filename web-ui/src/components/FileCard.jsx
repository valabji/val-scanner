import { thumbnailUrl } from '../api/files';

const CATEGORY_TEXT = {
  image: 'text-rose-400', audio: 'text-sky-400', video: 'text-violet-400',
  document: 'text-amber-400', archive: 'text-orange-400', code: 'text-emerald-400',
  other: 'text-muted',
};

export default function FileCard({ file, selected, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-stretch w-40 m-1 bg-panel rounded overflow-hidden text-left hover:scale-105 transition-transform ${selected ? 'ring-2 ring-accent' : ''}`}
    >
      <div className="h-40 bg-bg flex items-center justify-center overflow-hidden">
        {file.has_thumbnail ? (
          <img
            src={thumbnailUrl(file.id)}
            alt=""
            loading="lazy"
            className="object-cover w-full h-full"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
        ) : (
          <span className={`text-3xl ${CATEGORY_TEXT[file.category] || 'text-muted'}`}>
            {file.category[0].toUpperCase()}
          </span>
        )}
      </div>
      <div className="p-2">
        <div className="truncate text-sm" title={file.name}>{file.name}</div>
        <div className="text-xs text-muted">{file.size_human}</div>
      </div>
    </button>
  );
}
