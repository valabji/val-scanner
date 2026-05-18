import { get, post, del } from './_http';

export const listScans      = ()           => get('/api/scans');
export const startScan      = (body)       => post('/api/scan', body);
export const cancelScan     = (id)         => post(`/api/scan/${id}/cancel`);
export const deleteScan     = (id)         => del(`/api/scan/${id}`);
export const scanStreamUrl  = (id)         => `/api/scan/${id}/stream`;
