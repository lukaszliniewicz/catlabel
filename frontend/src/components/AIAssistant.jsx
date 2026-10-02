import React, { useEffect, useState } from 'react';
import {
  Send,
  Settings,
  Sparkles,
  Loader2,
  Copy,
  Check,
  History,
  Trash,
  Plus,
  Code,
  Image as ImageIcon,
  ClipboardPaste
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useStore } from '../store';
import { getPageIndices } from '../utils/canvasPages';
import { apiFetch } from '../utils/apiClient';

const MessageRow = ({ m }) => {
  if (m.role === 'tool') return null;
  if (m.role === 'assistant' && !m.content && m.tool_calls) return null;
  if (m.role === 'user' && Array.isArray(m.content)) return null;
  if (
    m.role === 'user' &&
    typeof m.content === 'string' &&
    (m.content.includes('[SYSTEM AUTO-INJECT]') || m.content.includes('[SYSTEM]'))
  ) {
    return null;
  }

  const isUser = m.role === 'user';

  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} my-2`}>
      {m.content && typeof m.content === 'string' && (
        <div
          className={`p-3 rounded-lg max-w-[90%] text-sm shadow-sm ${
            isUser
              ? 'bg-blue-600 text-white'
              : 'bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100'
          }`}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap">{m.content}</div>
          ) : (
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {m.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const buildCanvasStateSnapshot = (state) => ({
  __project_id__: state.currentProjectId,
  __project_revision__: state.currentProjectRevision,
  width: state.canvasWidth,
  height: state.canvasHeight,
  isRotated: state.isRotated,
  splitMode: state.splitMode,
  canvasBorder: state.canvasBorder,
  canvasBorderThickness: state.canvasBorderThickness,
  pageLayouts: state.pageLayouts,
  items: state.items,
  currentPage: state.currentPage,
  batchRecords: state.batchRecords,
  printCopies: state.printCopies,
  __dpi__: state.currentDpi || state.selectedPrinterInfo?.dpi || 203
});

const extractToolCallsFromResponse = (rawText) => {
  let jsonText = String(rawText || '').trim();

  const fencedMatch = jsonText.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  if (fencedMatch) {
    jsonText = fencedMatch[1].trim();
  }

  const firstBracket = jsonText.indexOf('[');
  const lastBracket = jsonText.lastIndexOf(']');
  if (firstBracket !== -1 && lastBracket > firstBracket) {
    jsonText = jsonText.slice(firstBracket, lastBracket + 1);
  }

  const parsed = JSON.parse(jsonText);
  if (Array.isArray(parsed)) {
    return parsed;
  }
  if (parsed && Array.isArray(parsed.tool_calls)) {
    return parsed.tool_calls;
  }

  throw new Error('Response is not a JSON array of tool calls.');
};

export default function AIAssistant() {
  const messages = useStore((state) => state.aiMessages);
  const setMessages = useStore((state) => state.setAiMessages);
  const input = useStore((state) => state.aiInput);
  const setInput = useStore((state) => state.setAiInput);
  const currentConvId = useStore((state) => state.aiConvId);
  const setCurrentConvId = useStore((state) => state.setAiConvId);
  const sessionUsage = useStore((state) => state.aiSessionUsage);
  const setSessionUsage = useStore((state) => state.setAiSessionUsage);
  const resetAiChat = useStore((state) => state.resetAiChat);
  const setShowAiConfig = useStore((state) => state.setShowAiConfig);
  const items = useStore((state) => state.items);
  const pageLayouts = useStore((state) => state.pageLayouts) || [];

  const aiMode = useStore((state) => state.aiMode);
  const setAiMode = useStore((state) => state.setAiMode);

  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [histories, setHistories] = useState([]);

  const [externalLoading, setExternalLoading] = useState(false);
  const externalIntent = useStore((state) => state.aiExternalIntent);
  const setExternalIntent = useStore((state) => state.setAiExternalIntent);
  const externalPrompt = useStore((state) => state.aiExternalPrompt);
  const setExternalPrompt = useStore((state) => state.setAiExternalPrompt);
  const externalResponse = useStore((state) => state.aiExternalResponse);
  const setExternalResponse = useStore((state) => state.setAiExternalResponse);
  const externalError = useStore((state) => state.aiExternalError);
  const setExternalError = useStore((state) => state.setAiExternalError);
  const externalNotice = useStore((state) => state.aiExternalNotice);
  const setExternalNotice = useStore((state) => state.setAiExternalNotice);
  const externalResults = useStore((state) => state.aiExternalResults);
  const setExternalResults = useStore((state) => state.setAiExternalResults);
  const [promptCopied, setPromptCopied] = useState(false);
  const [imageCopied, setImageCopied] = useState(false);

  const isEmpty = items.length === 0 && pageLayouts.every(l => !l.htmlContent || l.htmlContent.trim() === '');

  useEffect(() => {
    if (aiMode === 'live') {
      fetchHistories();
    }
  }, [aiMode]);

  const selectAiMode = (mode) => {
    setShowHistory(false);
    setAiMode(mode);
  };

  const fetchHistories = async () => {
    try {
      const res = await apiFetch('/api/ai/history');
      const data = await res.json();
      setHistories(data);
    } catch (e) {
      console.error('Failed to fetch AI histories', e);
    }
  };

  const handleCopyHistory = async () => {
    let out = '# CatLabel AI Session Debug Report\n\n';
    out += `**Session Tokens:** ${(sessionUsage.tokens || 0).toLocaleString()}\n`;
    out += `**Prompt Tokens:** ${(sessionUsage.promptTokens || 0).toLocaleString()}\n`;
    out += `**Completion Tokens:** ${(sessionUsage.completionTokens || 0).toLocaleString()}\n`;
    out += `**Estimated Cost:** $${Number(sessionUsage.cost || 0).toFixed(4)}\n\n`;
    out += '---\n\n';

    const sanitizeObj = (obj) => {
      if (typeof obj === 'string' && obj.startsWith('data:image/') && obj.length > 100) {
        return obj.substring(0, 50) + '...[TRUNCATED BASE64]';
      }
      if (Array.isArray(obj)) return obj.map(sanitizeObj);
      if (obj && typeof obj === 'object') {
        const nextObj = {};
        Object.keys(obj).forEach((key) => {
          nextObj[key] = sanitizeObj(obj[key]);
        });
        return nextObj;
      }
      return obj;
    };

    try {
      if (currentConvId) {
        const res = await apiFetch(`/api/ai/history/${currentConvId}/trace`);
        const traces = await res.json();
        out += '## RAW LLM TRACES (Database Logs)\n\n';
        out += `\`\`\`json\n${JSON.stringify(traces, null, 2)}\n\`\`\`\n\n`;
        out += '---\n\n';
      }

      out += '## UI MESSAGE HISTORY\n\n';
      messages.forEach((m) => {
        out += `### [${m.role.toUpperCase()}]\n\n`;

        if (m.role !== 'tool' && m.content) {
          if (typeof m.content === 'string') {
            out += `${m.content}\n\n`;
          } else if (Array.isArray(m.content)) {
            const textContent = m.content.find((c) => c.type === 'text')?.text || '';
            out += `${textContent}\n\n*[Base64 Image Attached]*\n\n`;
          }
        }

        if (m.tool_calls && m.tool_calls.length > 0) {
          m.tool_calls.forEach((tc) => {
            out += `**Tool Call:** \`${tc.function?.name || 'unknown'}\`\n\n`;
            out += '```json\n';
            try {
              const parsedArgs = JSON.parse(tc.function?.arguments || '{}');
              out += `${JSON.stringify(sanitizeObj(parsedArgs), null, 2)}\n`;
            } catch (_error) {
              let rawArgs = tc.function?.arguments || '';
              if (rawArgs.length > 500) rawArgs = `${rawArgs.substring(0, 200)}...[TRUNCATED]`;
              out += `${rawArgs}\n`;
            }
            out += '```\n\n';
          });
        }

        if (m.role === 'tool') {
          out += '> **Tool Result:**\n';
          out += `> ${(m.content || '').replace(/\n/g, '\n> ')}\n\n`;
        }
      });

      await navigator.clipboard.writeText(out);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error('Copy failed', e);
      alert('Failed to copy trace logs to clipboard.');
    }
  };

  const saveConversation = async (msgs, convId) => {
    try {
      if (convId) {
        await apiFetch(`/api/ai/history/${convId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: msgs })
        });
      }
    } catch (e) {
      console.error('Failed to save AI history', e);
    }
  };

  const loadHistory = async (id) => {
    try {
      const res = await apiFetch(`/api/ai/history/${id}`);
      const data = await res.json();
      setMessages(data.messages);
      setCurrentConvId(id);
      setShowHistory(false);
      setSessionUsage({ tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 });
    } catch (e) {
      console.error('Failed to load AI history', e);
    }
  };

  const deleteHistory = async (id) => {
    try {
      await apiFetch(`/api/ai/history/${id}`, { method: 'DELETE' });
      if (currentConvId === id) setCurrentConvId(null);
      fetchHistories();
    } catch (e) {
      console.error('Failed to delete AI history', e);
    }
  };

  const executeCanvasActions = (canvasState) => {
    (canvasState.__actions__ || []).forEach((action) => {
      if (action.action === 'print') {
        useStore.getState().printPages(getPageIndices(canvasState));
      } else if (action.action === 'refresh_projects') {
        useStore.getState().fetchProjects();
      } else if (action.action === 'loaded_project_id') {
        useStore.getState().setCurrentProjectId(action.project_id, action.revision);
      } else if (action.action === 'frontend_visual_preview') {
        window.setTimeout(() => {
          handleSendLive(
            '[SYSTEM AUTO-INJECT] Here is the visual preview of the canvas you requested. Evaluate it. If elements overlap, are out of bounds, or look bad, use tools to fix them. Otherwise, reply to the user.'
          );
        }, 600);
      }
    });
  };

  const applyCanvasState = (canvasState) => {
    if (!canvasState) return;

    const store = useStore.getState();
    store.hydrateCanvasState(canvasState);

    executeCanvasActions(canvasState);
  };

  async function handleSendLive(overrideText = null) {
    const storeState = useStore.getState();
    const isAutoReply = typeof overrideText === 'string';
    const textToSend = isAutoReply ? overrideText : (storeState.aiInput ?? input);
    const baseMessages = storeState.aiMessages ?? messages;

    if (!textToSend.trim()) return;

    setLoading(true);

    let activeConvId = storeState.aiConvId ?? currentConvId;
    if (!activeConvId) {
      try {
        const title = `${textToSend.substring(0, 30)}...`;
        const res = await apiFetch('/api/ai/history', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, messages: baseMessages })
        });
        const data = await res.json();
        activeConvId = data.id;
        setCurrentConvId(data.id);
        fetchHistories();
      } catch (e) {
        console.error('Failed to eagerly create conversation', e);
      }
    }

    const newMessages = [...baseMessages, { role: 'user', content: textToSend }];
    setMessages(newMessages);
    if (!isAutoReply) setInput('');

    try {
      const b64Image = await storeState.getStageB64();

      const res = await apiFetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: newMessages,
          canvas_state: buildCanvasStateSnapshot(storeState),
          mac_address: storeState.selectedPrinter || null,
          printer_info: storeState.selectedPrinterInfo || null,
          current_canvas_b64: b64Image ? b64Image.split(',')[1] : null,
          conv_id: activeConvId
        })
      });

      const data = await res.json();

      if (data.error) {
        setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${data.error}` }]);
      } else if (data.new_messages) {
        const finalMessages = [...newMessages, ...data.new_messages];
        setMessages(finalMessages);
        saveConversation(finalMessages, activeConvId);

        if (data.usage) {
          setSessionUsage((prev) => ({
            tokens: prev.tokens + (data.usage.total_tokens || 0),
            promptTokens: (prev.promptTokens || 0) + (data.usage.prompt_tokens || 0),
            completionTokens: (prev.completionTokens || 0) + (data.usage.completion_tokens || 0),
            cost: prev.cost + (data.usage.cost || 0)
          }));
        }

        if (data.canvas_state) {
          applyCanvasState(data.canvas_state);
        }
      }
    } catch (_error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Failed to connect to the AI Agent.' }
      ]);
    } finally {
      setLoading(false);
    }
  }

  const handleGenerateExternalPrompt = async () => {
    if (!externalIntent.trim()) return;

    setExternalLoading(true);
    setExternalError('');
    setExternalNotice('');
    setExternalResults([]);
    setPromptCopied(false);

    try {
      const storeState = useStore.getState();
      const res = await apiFetch('/api/ai/manual/prompt-builder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intent: externalIntent,
          canvas_state: buildCanvasStateSnapshot(storeState),
          mac_address: storeState.selectedPrinter || null,
          printer_info: storeState.selectedPrinterInfo || null
        })
      });

      const data = await res.json();
      setExternalPrompt(data.prompt || '');
      if (!data.prompt) {
        setExternalError('Server returned an empty prompt.');
      }
    } catch (error) {
      console.error('Failed to generate external AI prompt', error);
      setExternalError('Failed to generate prompt from server.');
    } finally {
      setExternalLoading(false);
    }
  };

  const handleCopyExternalPrompt = async () => {
    try {
      await navigator.clipboard.writeText(externalPrompt);
      setPromptCopied(true);
      setTimeout(() => setPromptCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy external prompt', error);
      alert('Failed to copy prompt to clipboard.');
    }
  };

  const handleExecuteExternal = async () => {
    if (!externalResponse.trim()) return;

    setExternalLoading(true);
    setExternalError('');
    setExternalNotice('');
    setExternalResults([]);

    let toolCalls = [];
    try {
      toolCalls = extractToolCallsFromResponse(externalResponse);
      if (!Array.isArray(toolCalls)) {
        throw new Error('Response is not a JSON array.');
      }
    } catch (_error) {
      setExternalError(
        'Invalid JSON array provided. Please ensure the pasted AI response contains the requested tool-call array.'
      );
      setExternalLoading(false);
      return;
    }

    try {
      const res = await apiFetch('/api/ai/manual/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_calls: toolCalls,
          canvas_state: buildCanvasStateSnapshot(useStore.getState())
        })
      });

      const data = await res.json();
      setExternalResults(data.execution_results || []);

      if (data.canvas_state) {
        applyCanvasState(data.canvas_state);
      }

      const resultList = data.execution_results || [];
      const errorCount = resultList.filter((result) => result.status !== 'success').length;
      if (resultList.length > 0) {
        setExternalNotice(
          errorCount > 0
            ? `Applied ${resultList.length} tool call(s) with ${errorCount} error(s).`
            : `Applied ${resultList.length} tool call(s) successfully.`
        );
      } else {
        setExternalNotice('No tool calls were executed.');
      }
    } catch (e) {
      console.error('Failed to execute external tool calls', e);
      setExternalError('Execution failed on the server.');
    } finally {
      setExternalLoading(false);
    }
  };

  const handleCopyCanvasImage = async () => {
    setExternalError('');

    try {
      if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
        throw new Error('Clipboard image writing is not supported in this browser.');
      }

      const b64 = await useStore.getState().getStageB64();
      if (!b64) {
        throw new Error('Failed to capture the canvas image.');
      }

      const response = await fetch(b64);
      const blob = await response.blob();
      const mimeType = blob.type || 'image/png';

      await navigator.clipboard.write([
        new ClipboardItem({
          [mimeType]: blob
        })
      ]);

      setImageCopied(true);
      setExternalNotice(
        'Canvas image copied to your clipboard. Paste it directly into ChatGPT or Claude with your correction notes.'
      );
      setTimeout(() => setImageCopied(false), 2000);
    } catch (e) {
      console.error('Failed to copy canvas image', e);
      alert(
        'Your browser does not support copying images directly to the clipboard. You can still capture the canvas manually and paste it into your LLM.'
      );
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-neutral-950">
      <style
        dangerouslySetInnerHTML={{
          __html: `
        .markdown-body p { margin-bottom: 0.75rem; }
        .markdown-body p:last-child { margin-bottom: 0; }
        .markdown-body ul { list-style-type: disc; padding-left: 1.5rem; margin-bottom: 0.75rem; }
        .markdown-body ol { list-style-type: decimal; padding-left: 1.5rem; margin-bottom: 0.75rem; }
        .markdown-body code { background-color: rgba(150,150,150,0.15); padding: 0.2rem 0.4rem; border-radius: 0.25rem; font-family: monospace; font-size: 0.9em; }
        .markdown-body pre { background-color: rgba(0,0,0,0.8); color: white; padding: 0.75rem; border-radius: 0.375rem; overflow-x: auto; margin-bottom: 0.75rem; font-family: monospace; }
        .markdown-body h1, .markdown-body h2, .markdown-body h3, .markdown-body h4 { font-weight: 700; margin-bottom: 0.5rem; margin-top: 1rem; }
        .markdown-body a { color: #3b82f6; text-decoration: underline; }
        .markdown-body strong { font-weight: 700; }
      `
        }}
      />

      <div className="pb-3 border-b border-neutral-100 dark:border-neutral-800 space-y-3 shrink-0">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-serif tracking-tight text-neutral-900 dark:text-white">
            <Sparkles size={18} className="text-blue-500" /> AI Assistant
          </h2>
          <button
            onClick={() => setShowAiConfig(true)}
            className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors"
            title="AI Settings"
          >
            <Settings size={16} />
          </button>
        </div>

        <div className="flex bg-neutral-100 dark:bg-neutral-900 p-1 rounded-md text-[10px] font-bold uppercase tracking-widest">
          <button
            onClick={() => selectAiMode('live')}
            className={`flex-1 py-2 rounded transition-colors ${
              aiMode === 'live'
                ? 'bg-white dark:bg-neutral-800 shadow-sm text-blue-600 dark:text-blue-400'
                : 'text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200'
            }`}
          >
            Live Agent (API)
          </button>
          <button
            onClick={() => selectAiMode('external')}
            className={`flex-1 py-2 rounded transition-colors ${
              aiMode === 'external'
                ? 'bg-white dark:bg-neutral-800 shadow-sm text-purple-600 dark:text-purple-400'
                : 'text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200'
            }`}
          >
            External (Copy/Paste)
          </button>
        </div>
      </div>

      {aiMode === 'live' ? (
        <>
          <div className="flex items-center justify-between py-3 border-b border-neutral-100 dark:border-neutral-800 shrink-0">
            <div className="text-[10px] uppercase tracking-widest font-bold text-neutral-400 dark:text-neutral-500">
              Uses your configured LiteLLM provider
            </div>
            <div className="flex gap-1">
              <button
                onClick={() => {
                  resetAiChat();
                  setShowHistory(false);
                }}
                className="p-1.5 text-neutral-400 hover:text-blue-500 transition-colors"
                title="New Chat"
              >
                <Plus size={16} />
              </button>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className={`p-1.5 transition-colors ${
                  showHistory
                    ? 'text-blue-500'
                    : 'text-neutral-400 hover:text-neutral-900 dark:hover:text-white'
                }`}
                title="Chat History"
              >
                <History size={16} />
              </button>
              <button
                onClick={handleCopyHistory}
                className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors"
                title="Copy Raw Session Trace"
              >
                {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
              </button>
            </div>
          </div>

          {showHistory ? (
            <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col">
              <button
                onClick={() => {
                  resetAiChat();
                  setShowHistory(false);
                }}
                className="mb-4 text-blue-500 font-bold text-xs uppercase tracking-widest flex items-center gap-2 px-3 py-2 border border-blue-200 dark:border-blue-900/50 bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/40 rounded transition-colors"
              >
                <Plus size={16} /> Start New Conversation
              </button>
              {histories.map((history) => (
                <div
                  key={history.id}
                  className="flex items-center justify-between p-3 border border-neutral-200 dark:border-neutral-800 mb-2 rounded cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors"
                  onClick={() => loadHistory(history.id)}
                >
                  <div className="text-sm font-medium truncate flex-1 dark:text-white pr-4">
                    {history.title}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteHistory(history.id);
                    }}
                    className="text-neutral-400 hover:text-red-500 transition-colors"
                  >
                    <Trash size={14} />
                  </button>
                </div>
              ))}
              {histories.length === 0 && (
                <div className="text-xs text-neutral-500 text-center mt-10">
                  No saved conversations yet.
                </div>
              )}
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col">
              {messages.map((m, i) => (
                <MessageRow key={i} m={m} />
              ))}
              {loading && (
                <div className="flex justify-start my-2">
                  <div className="p-3 rounded-lg bg-neutral-100 dark:bg-neutral-900 text-neutral-500 flex items-center gap-2 text-sm">
                    <Loader2 size={14} className="animate-spin text-blue-500" />
                    Thinking &amp; Executing Tools...
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="pt-3 border-t border-neutral-100 dark:border-neutral-800 mt-auto shrink-0">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendLive();
              }}
              className="flex gap-2"
            >
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={loading}
                placeholder="Ask AI to design a label..."
                className="flex-1 bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 transition-colors"
              />
              <button
                id="ai-submit-btn"
                type="submit"
                disabled={loading || !input.trim()}
                className="bg-blue-600 text-white p-2 hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                <Send size={18} />
              </button>
            </form>
            {(sessionUsage.tokens > 0 || sessionUsage.promptTokens > 0) && (
              <div className="flex justify-between items-center mt-2 px-1 text-[10px] uppercase tracking-widest font-bold text-neutral-400 dark:text-neutral-500">
                <span
                  title={`Prompt: ${(sessionUsage.promptTokens || 0).toLocaleString()} | Completion: ${(sessionUsage.completionTokens || 0).toLocaleString()}`}
                >
                  Session Tokens:{' '}
                  {(
                    (sessionUsage.tokens || 0) > 0
                      ? sessionUsage.tokens
                      : (sessionUsage.promptTokens || 0) + (sessionUsage.completionTokens || 0)
                  ).toLocaleString()}
                </span>
                <span title="Estimated API cost based on LiteLLM pricing">
                  Cost: {sessionUsage.cost > 0 ? `$${sessionUsage.cost.toFixed(4)}` : 'Unknown / Free'}
                </span>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col gap-5">
          <div className="text-[10px] text-neutral-500 leading-relaxed bg-purple-50 dark:bg-purple-900/10 p-3 rounded border border-purple-100 dark:border-purple-900/30">
            Use your own ChatGPT Plus or Claude Pro account without consuming CatLabel API credits.
            Generate the full tool-call prompt here, paste it into your external LLM, then paste the
            JSON tool-call response back below. You can also copy the current canvas as an image and
            paste it into the external chat for visual correction rounds.
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest">
              1. Describe the change you want
            </label>
            <textarea
              value={externalIntent}
              onChange={(e) => setExternalIntent(e.target.value)}
              placeholder={isEmpty ? "E.g. Design a shipping label for a fragile package." : "E.g. Move the product name up, make the barcode wider, and ensure nothing overlaps."}
              className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-3 text-sm dark:text-white focus:outline-none focus:border-purple-500 transition-colors min-h-[96px]"
            />
            <button
              onClick={handleGenerateExternalPrompt}
              disabled={externalLoading || !externalIntent.trim()}
              className="w-full bg-purple-600 text-white p-2 hover:bg-purple-700 transition-colors disabled:opacity-50 text-xs uppercase tracking-widest font-bold flex items-center justify-center gap-2"
            >
              {externalLoading ? <Loader2 size={14} className="animate-spin" /> : <Code size={14} />}
              Generate Prompt
            </button>
          </div>

          {externalPrompt && (
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest">
                2. Copy this prompt into ChatGPT or Claude
              </label>
              <textarea
                value={externalPrompt}
                readOnly
                className="w-full bg-neutral-50 dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-700 p-3 text-[10px] font-mono text-neutral-600 dark:text-neutral-300 min-h-[180px]"
              />
              <div className="flex gap-2">
                <button
                  onClick={handleCopyExternalPrompt}
                  className="flex-1 bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white p-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors text-xs flex items-center justify-center gap-2 border border-neutral-200 dark:border-neutral-800"
                >
                  {promptCopied ? (
                    <Check size={14} className="text-green-500" />
                  ) : (
                    <Copy size={14} />
                  )}
                  {promptCopied ? 'Prompt Copied' : 'Copy Prompt'}
                </button>
                <button
                  onClick={handleCopyCanvasImage}
                  className="flex-1 bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white p-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors text-xs flex items-center justify-center gap-2 border border-neutral-200 dark:border-neutral-800"
                >
                  {imageCopied ? (
                    <Check size={14} className="text-green-500" />
                  ) : (
                    <ImageIcon size={14} />
                  )}
                  {imageCopied ? 'Image Copied' : 'Copy Image'}
                </button>
              </div>
            </div>
          )}

          {externalPrompt && (
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest flex items-center gap-2">
                <ClipboardPaste size={12} />
                3. Paste the external AI response
              </label>
              <textarea
                value={externalResponse}
                onChange={(e) => setExternalResponse(e.target.value)}
                placeholder='Paste the JSON array here, e.g. [{"tool":"add_text_element","arguments":{...}}]'
                className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-3 text-sm font-mono dark:text-white focus:outline-none focus:border-purple-500 transition-colors min-h-[180px]"
              />

              {externalError && (
                <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-3 border border-red-200 dark:border-red-900/50">
                  {externalError}
                </div>
              )}

              {externalNotice && !externalError && (
                <div className="text-xs text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20 p-3 border border-green-200 dark:border-green-900/50">
                  {externalNotice}
                </div>
              )}

              <button
                onClick={handleExecuteExternal}
                disabled={externalLoading || !externalResponse.trim()}
                className="w-full bg-purple-600 text-white p-2 hover:bg-purple-700 transition-colors disabled:opacity-50 text-xs uppercase tracking-widest font-bold flex items-center justify-center gap-2"
              >
                {externalLoading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Sparkles size={14} />
                )}
                Apply Tool Calls
              </button>
            </div>
          )}

          {externalResults.length > 0 && (
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-neutral-400 dark:text-neutral-500 uppercase tracking-widest">
                Execution Results
              </label>
              <div className="border border-neutral-200 dark:border-neutral-800 divide-y divide-neutral-200 dark:divide-neutral-800">
                {externalResults.map((result) => (
                  <div
                    key={`${result.index}-${result.tool}`}
                    className="p-3 flex flex-col gap-1 bg-white dark:bg-neutral-950"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-bold dark:text-white">{result.tool}</span>
                      <span
                        className={`text-[10px] uppercase tracking-widest font-bold ${
                          result.status === 'success'
                            ? 'text-green-600 dark:text-green-400'
                            : 'text-red-600 dark:text-red-400'
                        }`}
                      >
                        {result.status}
                      </span>
                    </div>
                    <div className="text-[11px] text-neutral-500 dark:text-neutral-400 break-words">
                      {result.result}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
