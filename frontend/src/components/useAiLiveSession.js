import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { apiJson, isArrayPayload } from '../utils/apiClient';
import { isHistoryList, isHistoryDetail, isConversationCreated, isAiAcknowledgement, isChatResult } from '../domain/ai';
import { buildAiCanvasSnapshot, applyAiCanvasResult } from '../utils/aiCanvas';
import { buildAiTranscript } from '../utils/aiTranscript';

const AUTO_PREVIEW_MESSAGE = '[SYSTEM AUTO-INJECT] Here is the visual preview of the canvas you requested. Evaluate it. If elements overlap, are out of bounds, or look bad, use tools to fix them. Otherwise, reply to the user.';
const MAX_VISUAL_ROUNDS = 3;

export default function useAiLiveSession(owner) {
  const messages = useStore(state => state.aiMessages), input = useStore(state => state.aiInput);
  const sessionUsage = useStore(state => state.aiSessionUsage), aiMode = useStore(state => state.aiMode);
  const [showHistory, setShowHistory] = useState(false), [histories, setHistories] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true), [historyError, setHistoryError] = useState('');
  const [historyVersion, setHistoryVersion] = useState(0), [pendingDelete, setPendingDelete] = useState(null);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef(null);
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  useEffect(() => {
    if (aiMode !== 'live') return;
    const controller = new AbortController();
    apiJson('/api/ai/history', { signal: controller.signal }, { validate: isHistoryList }).then(data => {
      if (!controller.signal.aborted) { setHistories(data); setHistoryError(''); }
    }).catch(error => { if (!controller.signal.aborted) setHistoryError(error.message || 'Could not load conversations.'); })
      .finally(() => { if (!controller.signal.aborted) setHistoryLoading(false); });
    return () => controller.abort();
  }, [aiMode, historyVersion]);
  const refreshHistories = () => { setHistoryLoading(true); setHistoryVersion(value => value + 1); };
  const resetAiChat = () => { useStore.getState().resetAiChat(); setShowHistory(false); setPendingDelete(null); setCopied(false); };

  const loadHistory = async id => {
    const task = owner.begin('history'); if (!task) return;
    try {
      const data = await apiJson(`/api/ai/history/${id}`, { signal: task.controller.signal }, { validate: isHistoryDetail });
      if (data.id !== id) throw new Error('The server returned a different conversation.');
      if (!owner.finish(task)) return;
      const store = useStore.getState(); store.setAiMessages(data.messages); store.setAiConvId(id);
      store.setAiSessionUsage({ tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 }); setShowHistory(false);
    } catch (error) { if (owner.isCurrent(task)) owner.setNotice(error.message || 'Could not open the conversation.'); }
    finally { owner.finish(task); }
  };
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const task = owner.begin('history-delete'); if (!task) return;
    const id = pendingDelete.id;
    try {
      await apiJson(`/api/ai/history/${id}`, { method: 'DELETE', signal: task.controller.signal }, { validate: isAiAcknowledgement });
      if (!owner.finish(task)) return;
      if (useStore.getState().aiConvId === id) useStore.getState().setAiConvId(null);
      setPendingDelete(null); refreshHistories();
    } catch (error) { if (owner.isCurrent(task)) owner.setNotice(error.message || 'Could not delete the conversation.'); }
    finally { owner.finish(task); }
  };
  const handleCopyHistory = async () => {
    const task = owner.begin('copy-history'); if (!task) return;
    const state = useStore.getState();
    try {
      const traces = state.aiConvId ? await apiJson(`/api/ai/history/${state.aiConvId}/trace`, { signal: task.controller.signal }, { validate: isArrayPayload }) : null;
      if (!owner.isCurrent(task)) return;
      await navigator.clipboard.writeText(buildAiTranscript(state.aiMessages, state.aiSessionUsage, traces));
      if (!owner.isCurrent(task)) return;
      setCopied(true); clearTimeout(copyTimer.current); copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch (error) { if (owner.isCurrent(task)) owner.setNotice(error.message || 'Could not copy the session trace.'); }
    finally { owner.finish(task); }
  };

  async function handleSendLive(overrideText = null, visualRound = 0) {
    const state = useStore.getState(), isAutoReply = typeof overrideText === 'string';
    const text = isAutoReply ? overrideText : state.aiInput;
    if (!text.trim()) return;
    const task = owner.begin('live'); if (!task) return;
    let activeConvId = state.aiConvId, previewRequested = false, accepted = false;
    const newMessages = [...state.aiMessages, { role: 'user', content: text }];
    state.setAiMessages(newMessages); if (!isAutoReply) state.setAiInput('');
    try {
      if (!activeConvId) {
        try {
          const created = await apiJson('/api/ai/history', { method: 'POST', signal: task.controller.signal,
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: `${text.slice(0, 30)}...`, messages: state.aiMessages }) }, { validate: isConversationCreated });
          if (!owner.isCurrent(task)) return;
          activeConvId = created.id; owner.adoptConversation(task, activeConvId); refreshHistories();
        } catch (error) {
          if (!owner.isCurrent(task)) return;
          owner.setNotice(`Conversation history could not be created: ${error.message || 'request failed'}. This reply will not be saved.`);
        }
      }
      const image = await state.getStageB64();
      if (!owner.isCurrent(task)) return;
      const data = await apiJson('/api/ai/chat', { method: 'POST', signal: task.controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: newMessages,
          canvas_state: buildAiCanvasSnapshot(state), mac_address: state.selectedPrinter || null,
          printer_info: state.selectedPrinterInfo || null, current_canvas_b64: image ? image.split(',')[1] : null, conv_id: activeConvId }) },
      { timeoutMs: 120_000, validate: isChatResult });
      if (!owner.isCurrent(task)) return;
      if (data.error) { useStore.getState().setAiMessages([...newMessages, { role: 'assistant', content: `Error: ${data.error}` }]); return; }
      const finalMessages = [...newMessages, ...data.new_messages];
      if (activeConvId) {
        try {
          await apiJson(`/api/ai/history/${activeConvId}`, { method: 'PUT', signal: task.controller.signal,
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: finalMessages }) }, { validate: isAiAcknowledgement });
        } catch (error) { if (owner.isCurrent(task)) owner.setNotice(`The reply was received, but conversation saving failed: ${error.message || 'request failed'}.`); }
      }
      accepted = owner.finish(task); if (!accepted) return;
      const store = useStore.getState(); store.setAiMessages(finalMessages);
      if (data.usage) store.setAiSessionUsage(previous => ({
        tokens: previous.tokens + (data.usage.total_tokens || 0), promptTokens: previous.promptTokens + (data.usage.prompt_tokens || 0),
        completionTokens: previous.completionTokens + (data.usage.completion_tokens || 0), cost: previous.cost + (data.usage.cost || 0)
      }));
      previewRequested = applyAiCanvasResult(data.canvas_state, owner.setNotice);
    } catch (error) {
      if (accepted || owner.isCurrent(task)) {
        owner.setNotice(error.message || 'The AI request failed.');
        useStore.getState().setAiMessages(previous => [...previous, { role: 'assistant', content: error.message || 'The AI request failed.' }]);
      }
    } finally { owner.finish(task); }
    if (previewRequested) {
      if (visualRound < MAX_VISUAL_ROUNDS) owner.schedulePreview(() => { void handleSendLive(AUTO_PREVIEW_MESSAGE, visualRound + 1); });
      else owner.setNotice('Visual review stopped after three rounds. Send a new request to continue.');
    }
  }
  return { messages, input, sessionUsage, showHistory, setShowHistory, histories, historyLoading, historyError, copied,
    resetAiChat, refreshHistories, loadHistory, deleteHistory: id => setPendingDelete(histories.find(history => history.id === id) || null),
    pendingDelete, setPendingDelete, confirmDelete, handleCopyHistory, handleSendLive };
}
