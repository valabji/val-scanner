import { get } from './_http';

export const listFolders = (scanId) => get('/api/folders', { scan_id: scanId });
export const listSimilar = (scanId) => get('/api/similar', { scan_id: scanId });
