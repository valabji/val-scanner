export default function TagChip({ tag }) {
  const cls =
    tag.startsWith('hidden') || tag === 'dotfile' ? 'bg-muted/30 text-muted' :
    tag === 'large-file' || tag === 'small-file'  ? 'bg-amber-500/20 text-amber-300' :
                                                    'bg-accent/20 text-accent';
  return <span className={`px-2 py-0.5 rounded text-xs font-mono ${cls}`}>{tag}</span>;
}
