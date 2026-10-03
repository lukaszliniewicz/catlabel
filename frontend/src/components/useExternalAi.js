import { useEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useStore } from '../store';
import { apiJson } from '../utils/apiClient';
import { extractToolCalls, isExternalPrompt, isManualResult } from '../domain/ai';
import { buildAiCanvasSnapshot, applyAiCanvasResult } from '../utils/aiCanvas';

export default function useExternalAi(owner) {
  const fields = useStore(useShallow(state => ({
    externalIntent: state.aiExternalIntent, setExternalIntent: state.setAiExternalIntent,
    externalPrompt: state.aiExternalPrompt, externalResponse: state.aiExternalResponse, setExternalResponse: state.setAiExternalResponse,
    externalError: state.aiExternalError, externalNotice: state.aiExternalNotice, externalResults: state.aiExternalResults,
    promptContext: state.aiExternalPromptContext
  })));
  const [promptCopied, setPromptCopied] = useState(false), [imageCopied, setImageCopied] = useState(false);
  const timers = useRef([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const clearFeedback = () => {
    const store = useStore.getState(); store.setAiExternalError(''); store.setAiExternalNotice(''); store.setAiExternalResults([]);
  };
  const handleGenerateExternalPrompt = async () => {
    const state = useStore.getState(); if (!state.aiExternalIntent.trim()) return;
    const task = owner.begin('external-prompt'); if (!task) return;
    clearFeedback(); setPromptCopied(false);
    try {
      const data = await apiJson('/api/ai/manual/prompt-builder', { method: 'POST', signal: task.controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent: state.aiExternalIntent,
          canvas_state: buildAiCanvasSnapshot(state), mac_address: state.selectedPrinter || null, printer_info: state.selectedPrinterInfo || null }) }, { validate: isExternalPrompt });
      if (owner.finish(task)) useStore.getState().setAiExternalPrompt(data.prompt, task.expected);
    } catch (error) { if (owner.isCurrent(task)) useStore.getState().setAiExternalError(error.message || 'Could not generate the prompt.'); }
    finally { owner.finish(task); }
  };
  const handleExecuteExternal = async () => {
    const state = useStore.getState(); if (!state.aiExternalResponse.trim()) return;
    if (!owner.isContextCurrent(state.aiExternalPromptContext)) {
      state.setAiExternalError('The design or conversation changed since this prompt was generated. Generate a new prompt before applying its response.'); return;
    }
    let toolCalls;
    try { toolCalls = extractToolCalls(state.aiExternalResponse); }
    catch { state.setAiExternalError('Invalid tool-call JSON. Paste the requested array or an object containing tool_calls.'); return; }
    const task = owner.begin('external-execute'); if (!task) return;
    clearFeedback();
    let accepted = false;
    try {
      const data = await apiJson('/api/ai/manual/execute', { method: 'POST', signal: task.controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool_calls: toolCalls, canvas_state: buildAiCanvasSnapshot(state) }) },
      { timeoutMs: 120_000, validate: isManualResult });
      accepted = owner.finish(task); if (!accepted) return;
      const store = useStore.getState(); store.setAiExternalResults(data.execution_results);
      applyAiCanvasResult(data.canvas_state, owner.setNotice);
      const errors = data.execution_results.filter(result => result.status === 'error').length;
      const pending = data.execution_results.filter(result => result.status === 'confirmation_required').length;
      store.setAiExternalNotice(data.execution_results.length
        ? `Processed ${data.execution_results.length} tool call(s)${errors ? ` with ${errors} error(s)` : ''}${pending ? `; ${pending} require confirmation in the app` : ''}. Review the results and design.`
        : 'No tool calls were executed.');
    } catch (error) { if (accepted || owner.isCurrent(task)) useStore.getState().setAiExternalError(error.message || 'The tool-call request failed.'); }
    finally { owner.finish(task); }
  };
  const handleCopyExternalPrompt = async () => {
    const task = owner.begin('external-copy'); if (!task) return;
    try {
      await navigator.clipboard.writeText(useStore.getState().aiExternalPrompt);
      if (!owner.isCurrent(task)) return;
      setPromptCopied(true); timers.current.push(setTimeout(() => setPromptCopied(false), 2000));
    } catch (error) { if (owner.isCurrent(task)) useStore.getState().setAiExternalError(error.message || 'Could not copy the prompt.'); }
    finally { owner.finish(task); }
  };
  const handleCopyCanvasImage = async () => {
    const task = owner.begin('external-image'); if (!task) return;
    useStore.getState().setAiExternalError('');
    try {
      if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') throw new Error('This browser cannot copy images. Use a screenshot of the label instead.');
      const image = await useStore.getState().getStageB64();
      if (!owner.isCurrent(task)) return;
      if (!image) throw new Error('Could not capture the label image.');
      const response = await fetch(image), blob = await response.blob();
      if (!owner.isCurrent(task)) return;
      await navigator.clipboard.write([new ClipboardItem({ [blob.type || 'image/png']: blob })]);
      if (!owner.isCurrent(task)) return;
      setImageCopied(true); useStore.getState().setAiExternalNotice('Label image copied. Paste it into your external chat with your correction notes.');
      timers.current.push(setTimeout(() => setImageCopied(false), 2000));
    } catch (error) { if (owner.isCurrent(task)) useStore.getState().setAiExternalError(error.message || 'Could not copy the label image.'); }
    finally { owner.finish(task); }
  };
  const promptCurrent = Boolean(fields.promptContext) && Object.keys(fields.promptContext).every(key => owner.context[key] === fields.promptContext[key]);
  return { ...fields, promptCopied, imageCopied, promptCurrent,
    handleGenerateExternalPrompt, handleExecuteExternal, handleCopyExternalPrompt, handleCopyCanvasImage };
}
