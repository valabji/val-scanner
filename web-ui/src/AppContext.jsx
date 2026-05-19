import { createContext, useContext, useState, useMemo } from 'react';

const AppCtx = createContext(null);

export function AppContextProvider({ children }) {
  const [activeScanId, setActiveScanId] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const value = useMemo(
    () => ({ activeScanId, setActiveScanId, selectedFile, setSelectedFile }),
    [activeScanId, selectedFile],
  );
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApp() {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error('useApp must be used inside AppContextProvider');
  return ctx;
}
