export const withHistory = (config) => {
  let historyTimeout;
  let storedPrevState = null;

  return (set, get, api) => {
    const historySet = (args, replace, options = {}) => {
      if (options.history === 'reset') {
        const patch = typeof args === 'function' ? args(get()) : args;
        clearTimeout(historyTimeout);
        storedPrevState = null;
        set({
          ...patch,
          history: [],
          historyIndex: -1,
          canUndo: false,
          canRedo: false,
          _isUndoRedo: false
        }, replace, options);
        return;
      }

      if (options.history === 'skip') {
        set(args, replace, options);
        return;
      }

      if (!storedPrevState) {
        storedPrevState = get();
      }

      set(args, replace, options);
      const nextState = get();

      // If this change was triggered by undo/redo, strip the flag, reset the baseline, and exit.
      if (nextState._isUndoRedo) {
        set({ _isUndoRedo: false });
        storedPrevState = null;
        return;
      }

      clearTimeout(historyTimeout);
      historyTimeout = setTimeout(() => {
        const finalState = get();
        const relevantKeys = [
          'items',
          'canvasWidth',
          'canvasHeight',
          'currentDpi',
          'isRotated',
          'splitMode',
          'canvasBorder',
          'canvasBorderThickness',
          'pageLayouts',
          'batchRecords'
        ];
        let changed = false;

        for (const key of relevantKeys) {
          if (storedPrevState[key] !== finalState[key]) {
            changed = true;
            break;
          }
        }

        if (changed) {
          const snap = {};
          for (const key of relevantKeys) {
            snap[key] = finalState[key];
          }

          const currentHistory = finalState.history || [];
          const currentIndex = finalState.historyIndex !== undefined ? finalState.historyIndex : -1;

          // Truncate future history if the user makes a new change after undoing
          let newHistory = currentHistory.slice(0, currentIndex + 1);

          // If this is the very first change, push the original baseline state first
          if (newHistory.length === 0) {
            const prevSnap = {};
            for (const key of relevantKeys) {
              prevSnap[key] = storedPrevState[key];
            }
            newHistory.push(prevSnap);
          }

          newHistory.push(snap);

          // Limit stack to 50 items to prevent memory bloat
          if (newHistory.length > 50) newHistory.shift();

          set({
            history: newHistory,
            historyIndex: newHistory.length - 1,
            canUndo: newHistory.length > 1,
            canRedo: false
          });
        }

        storedPrevState = null;
      }, 400);
    };

    return config(historySet, get, api);
  };
};
