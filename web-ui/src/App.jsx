import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { AppContextProvider } from './AppContext';
import ScansPage from './pages/ScansPage';
import FilesPage from './pages/FilesPage';
import FoldersPage from './pages/FoldersPage';
import SimilarPage from './pages/SimilarPage';
import DetailPanel from './pages/DetailPanel';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

const tabLink = ({ isActive }) =>
  `px-3 py-2 text-sm ${isActive ? 'text-accent border-b-2 border-accent' : 'text-muted hover:text-text'}`;

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppContextProvider>
          <div className="flex flex-col h-screen">
            <header className="bg-panel px-4 py-3 flex items-center gap-4">
              <h1 className="text-lg font-semibold">valscanner</h1>
              <nav className="flex">
                <NavLink to="/"        end className={tabLink}>Scans</NavLink>
                <NavLink to="/files"     className={tabLink}>Files</NavLink>
                <NavLink to="/folders"   className={tabLink}>Folders</NavLink>
                <NavLink to="/similar"   className={tabLink}>Similar</NavLink>
              </nav>
            </header>
            <main className="flex-1 overflow-auto">
              <Routes>
                <Route path="/"        element={<ScansPage />} />
                <Route path="/files"   element={<FilesPage />} />
                <Route path="/folders" element={<FoldersPage />} />
                <Route path="/similar" element={<SimilarPage />} />
              </Routes>
            </main>
            <DetailPanel />
          </div>
        </AppContextProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
