import { useEffect, useState } from 'react';
import { useStore } from '../store';
import { ignoreCanvasShortcut } from '../utils/canvasShortcuts';

export default function useCanvasKeyboard() {
  const [isPanning, setIsPanning] = useState(false);
  useEffect(() => {
    const keyDown = event => {
      if (ignoreCanvasShortcut(event)) return;
      if (event.code === 'Space') { event.preventDefault(); setIsPanning(true); }
      const { selectedIds, deleteSelectedItems, moveSelectedItems, undo, redo } = useStore.getState();
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault(); if (event.shiftKey) redo(); else undo(); return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') { event.preventDefault(); redo(); return; }
      if (!selectedIds.length) return;
      if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); deleteSelectedItems(); }
      const step = event.shiftKey ? 10 : 1;
      if (event.key === 'ArrowUp') { event.preventDefault(); moveSelectedItems(0, -step); }
      if (event.key === 'ArrowDown') { event.preventDefault(); moveSelectedItems(0, step); }
      if (event.key === 'ArrowLeft') { event.preventDefault(); moveSelectedItems(-step, 0); }
      if (event.key === 'ArrowRight') { event.preventDefault(); moveSelectedItems(step, 0); }
    };
    const keyUp = event => { if (event.code === 'Space') setIsPanning(false); };
    const stopPan = () => setIsPanning(false);
    const visibility = () => { if (document.hidden) stopPan(); };
    window.addEventListener('keydown', keyDown); window.addEventListener('keyup', keyUp);
    window.addEventListener('blur', stopPan); document.addEventListener('visibilitychange', visibility);
    return () => {
      window.removeEventListener('keydown', keyDown); window.removeEventListener('keyup', keyUp);
      window.removeEventListener('blur', stopPan); document.removeEventListener('visibilitychange', visibility);
    };
  }, []);
  return isPanning;
}
