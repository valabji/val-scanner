import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AppContextProvider, useApp } from '../AppContext';
import DetailPanel from '../pages/DetailPanel';

function SeedSelection({ file }) {
  const { setSelectedFile } = useApp();
  return <button onClick={() => setSelectedFile(file)}>seed</button>;
}

describe('DetailPanel', () => {
  it('opens when a file is selected and closes on ESC', () => {
    const file = {
      id: 1, name: 'foo.txt', path: '/tmp/foo.txt', size: 5, size_human: '5 B',
      category: 'document', tags: ['small-file'], has_thumbnail: false,
    };
    render(
      <AppContextProvider>
        <SeedSelection file={file} />
        <DetailPanel />
      </AppContextProvider>,
    );

    fireEvent.click(screen.getByText('seed'));
    expect(screen.getByRole('dialog', { name: /file details/i })).toBeInTheDocument();
    expect(screen.getByText('foo.txt')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByText('foo.txt')).not.toBeInTheDocument();
  });
});
