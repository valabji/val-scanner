import { get, post } from './_http';

export const listFiles    = (params) => get('/api/files', params);
export const thumbnailUrl = (id)     => `/api/thumbnail/${id}`;
export const sampleUrl    = (id)     => `/api/sample/${id}`;
export const revealFile   = (id)     => post('/api/reveal', { file_id: id });
