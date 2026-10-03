import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';

const snapshot = state => ({
  documentSessionId: state.documentSessionId, documentRevision: state.documentRevision,
  currentPage: state.currentPage, aiConvId: state.aiConvId, aiSessionVersion: state.aiSessionVersion,
  aiMode: state.aiMode, selectedPrinter: state.selectedPrinter, selectedPrinterInfo: state.selectedPrinterInfo
});
const matches = (state, expected) => Object.keys(expected).every(key => state[key] === expected[key]);

export default function useAiRequestOwner() {
  const context = useStore(useShallow(snapshot));
  const activeRef = useRef(null);
  const scheduledRef = useRef(null);
  const [busyKind, setBusyKind] = useState(null);
  const [notice, setNotice] = useState('');
  const cancel = useCallback((message = 'Assistant request cancelled. Server work already started may continue.') => {
    const active = activeRef.current;
    activeRef.current = null;
    if (active) { active.controller.abort(new Error(message)); setBusyKind(null); setNotice(message); }
    if (scheduledRef.current) { clearTimeout(scheduledRef.current.timer); scheduledRef.current = null; }
  }, []);
  useEffect(() => {
    const unsubscribe = useStore.subscribe(state => {
      const expected = activeRef.current?.expected || scheduledRef.current?.expected;
      if (expected && !matches(state, expected)) cancel('The design or conversation changed. The late assistant reply will not be applied. Server work already started may continue.');
    });
    return () => {
      unsubscribe();
      const active = activeRef.current; activeRef.current = null;
      active?.controller.abort(new Error('Assistant closed.'));
      if (scheduledRef.current) { clearTimeout(scheduledRef.current.timer); scheduledRef.current = null; }
    };
  }, [cancel]);
  const begin = useCallback(kind => {
    if (activeRef.current) return null;
    const task = { kind, expected: snapshot(useStore.getState()), controller: new AbortController() };
    activeRef.current = task; setBusyKind(kind); setNotice('');
    return task;
  }, []);
  const isCurrent = useCallback(task => activeRef.current === task && !task.controller.signal.aborted && matches(useStore.getState(), task.expected), []);
  const finish = useCallback(task => {
    if (activeRef.current !== task) return false;
    const accepted = !task.controller.signal.aborted && matches(useStore.getState(), task.expected);
    activeRef.current = null; setBusyKind(null); return accepted;
  }, []);
  const adoptConversation = useCallback((task, id) => {
    if (activeRef.current !== task) return false;
    task.expected.aiConvId = id; useStore.getState().setAiConvId(id); return true;
  }, []);
  const schedulePreview = useCallback(callback => {
    if (scheduledRef.current) clearTimeout(scheduledRef.current.timer);
    const scheduled = { expected: snapshot(useStore.getState()), timer: null };
    scheduled.timer = setTimeout(() => {
      if (scheduledRef.current !== scheduled) return;
      scheduledRef.current = null;
      if (matches(useStore.getState(), scheduled.expected)) callback();
    }, 0);
    scheduledRef.current = scheduled;
  }, []);
  const isContextCurrent = useCallback(expected => Boolean(expected) && matches(useStore.getState(), expected), []);
  return { context, busyKind, notice, setNotice, begin, isCurrent, isContextCurrent, finish, adoptConversation, schedulePreview, cancel };
}
