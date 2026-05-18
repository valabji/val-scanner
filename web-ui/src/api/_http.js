const qs = (params) => {
  if (!params) return '';
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    usp.append(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : '';
};

async function handle(r) {
  if (r.ok) return r.status === 204 ? null : r.json();
  let body = {};
  try { body = await r.json(); } catch {}
  const err = new Error(body.detail || r.statusText);
  err.status = r.status;
  err.code = body.error || 'http_error';
  err.body = body;
  throw err;
}

export const get  = (url, params) => fetch(url + qs(params)).then(handle);
export const post = (url, body) => fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: body == null ? undefined : JSON.stringify(body),
}).then(handle);
export const del  = (url) => fetch(url, { method: 'DELETE' }).then(handle);
