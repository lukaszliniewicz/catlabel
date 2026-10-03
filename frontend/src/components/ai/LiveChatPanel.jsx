import React from 'react';
import { Plus, Trash, Loader2, Send } from 'lucide-react';
import ChatMessage from './ChatMessage';

export default function LiveChatPanel({ showHistory, histories, historyLoading, historyError, busy, resetAiChat, setShowHistory, loadHistory, deleteHistory, messages, loading, input, setInput, handleSendLive, sessionUsage }) {
  return <>
          {historyError && <p role="alert" className="text-xs text-red-700 dark:text-red-300">{historyError}</p>}
          {historyLoading && showHistory && <p role="status" className="text-xs">Loading conversations…</p>}
          {showHistory ? (
            <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col">
              <button
                onClick={() => {
                  resetAiChat();
                  setShowHistory(false);
                }}
                className="mb-4 text-blue-500 font-bold text-xs uppercase tracking-widest flex items-center gap-2 px-3 py-2 border border-blue-200 dark:border-blue-900/50 bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/40 rounded-sm transition-colors"
              >
                <Plus size={16} /> Start New Conversation
              </button>
              {histories.map((history) => (
                <div
                  key={history.id}
                  className="flex items-center justify-between p-3 border border-neutral-200 dark:border-neutral-800 mb-2 rounded-sm cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors"
                >
                  <button type="button" disabled={busy} onClick={() => loadHistory(history.id)} className="min-h-11 text-left text-sm font-medium truncate flex-1 dark:text-white pr-4">
                    {history.title}
                  </button>
                  <button type="button" disabled={busy} aria-label={`Delete conversation ${history.title}`}
                    onClick={() => deleteHistory(history.id)}
                    className="min-h-11 min-w-11 text-neutral-600 dark:text-neutral-300 hover:text-red-500 transition-colors"
                  >
                    <Trash size={14} />
                  </button>
                </div>
              ))}
              {histories.length === 0 && !historyLoading && (
                <div className="text-xs text-neutral-500 text-center mt-10">
                  No saved conversations yet.
                </div>
              )}
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col">
              {messages.map((m, i) => (
                <ChatMessage key={i} m={m} />
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
                aria-label="Message to AI assistant"
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={busy}
                placeholder="Ask AI to design a label..."
                className="flex-1 bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-hidden focus:border-blue-500 transition-colors"
              />
              <button
                id="ai-submit-btn"
                aria-label="Send message to AI assistant"
                type="submit"
                disabled={busy || !input.trim()}
                className="min-h-11 min-w-11 bg-blue-600 text-white p-2 hover:bg-blue-700 transition-colors disabled:opacity-50"
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
  </>;
}
