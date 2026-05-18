import { useCallback, useRef } from 'react';
import { startScan, scanStreamUrl } from '../api/scans';

export function useScanProgress({ onProgress, onDone, onError }) {
  const esRef = useRef(null);

  const start = useCallback(async (body) => {
    const { scan_id } = await startScan(body);
    const es = new EventSource(scanStreamUrl(scan_id));
    esRef.current = es;

    es.onmessage = (e) => {
      let data;
      try { data = JSON.parse(e.data); } catch { return; }
      if (data.done || data.cancelled || data.error) {
        onDone?.(data);
        es.close();
        esRef.current = null;
      } else {
        onProgress?.(data);
      }
    };

    es.onerror = (err) => {
      onError?.(err);
      es.close();
      esRef.current = null;
    };

    return scan_id;
  }, [onProgress, onDone, onError]);

  const stop = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  return { start, stop };
}
