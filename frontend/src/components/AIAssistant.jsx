import React from 'react';
import { Settings, Sparkles, Copy, Check, History, Plus } from 'lucide-react';
import { useStore } from '../store';
import LiveChatPanel from './ai/LiveChatPanel';
import ExternalAiPanel from './ai/ExternalAiPanel';
import useAiRequestOwner from './useAiRequestOwner';
import useAiLiveSession from './useAiLiveSession';
import useExternalAi from './useExternalAi';
import ConfirmActionDialog from './ConfirmActionDialog';
import './ai/chat.css';

export default function AIAssistant() {
  const aiMode = useStore(state => state.aiMode), items = useStore(state => state.items), pageLayouts = useStore(state => state.pageLayouts);
  const owner = useAiRequestOwner(), live = useAiLiveSession(owner), external = useExternalAi(owner);
  const selectAiMode = mode => { if (mode !== aiMode) owner.cancel('Assistant mode changed. A late reply will not be applied.'); live.setShowHistory(false); useStore.getState().setAiMode(mode); };
  const livePanelProps = { ...live, loading: owner.busyKind === 'live', busy: Boolean(owner.busyKind), setInput: useStore(state => state.setAiInput) };
  const externalPanelProps = { ...external, isEmpty: items.length === 0 && pageLayouts.every(page => !page.htmlContent?.trim()),
    externalLoading: Boolean(owner.busyKind?.startsWith('external')), busy: Boolean(owner.busyKind) };
  return (
    <div className="flex flex-col h-full bg-white dark:bg-neutral-950">


      <div className="pb-3 border-b border-neutral-100 dark:border-neutral-800 space-y-3 shrink-0">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-serif tracking-tight text-neutral-900 dark:text-white">
            <Sparkles size={18} className="text-blue-500" /> AI Assistant
          </h2>
          <button
            onClick={() => useStore.getState().setShowAiConfig(true)}
            className="min-h-11 min-w-11 p-1.5 text-neutral-600 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-white transition-colors"
            title="AI Settings"
          >
            <Settings size={16} />
          </button>
        </div>

        <div className="flex bg-neutral-100 dark:bg-neutral-900 p-1 rounded-md text-[10px] font-bold uppercase tracking-widest">
          <button
            onClick={() => selectAiMode('live')}
            aria-pressed={aiMode === 'live'}
            className={`min-h-11 flex-1 py-2 rounded transition-colors ${
              aiMode === 'live'
                ? 'bg-white dark:bg-neutral-800 shadow-xs text-blue-600 dark:text-blue-400'
                : 'text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200'
            }`}
          >
            Live Agent (API)
          </button>
          <button
            onClick={() => selectAiMode('external')}
            aria-pressed={aiMode === 'external'}
            className={`min-h-11 flex-1 py-2 rounded transition-colors ${
              aiMode === 'external'
                ? 'bg-white dark:bg-neutral-800 shadow-xs text-purple-600 dark:text-purple-400'
                : 'text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200'
            }`}
          >
            External (Copy/Paste)
          </button>
        </div>
      </div>

      {owner.notice && <p role="status" className="my-2 text-xs text-neutral-800 dark:text-neutral-200">{owner.notice}</p>}
      {owner.busyKind && <button type="button" onClick={() => owner.cancel()} className="min-h-11 border border-neutral-500 px-3 text-sm">Cancel assistant request</button>}
      {aiMode === 'live' ? (
        <>
          <div className="flex items-center justify-between py-3 border-b border-neutral-100 dark:border-neutral-800 shrink-0">
            <div className="text-[10px] uppercase tracking-widest font-bold text-neutral-600 dark:text-neutral-300">
              Uses your configured LiteLLM provider
            </div>
            <div className="flex gap-1">
              <button
                onClick={() => {
                  live.resetAiChat();
                  live.setShowHistory(false);
                }}
                className="min-h-11 min-w-11 p-1.5 text-neutral-600 dark:text-neutral-300 hover:text-blue-500 transition-colors"
                title="New Chat"
              >
                <Plus size={16} />
              </button>
              <button
                onClick={() => live.setShowHistory(!live.showHistory)}
                className={`min-h-11 min-w-11 p-1.5 transition-colors ${
                  live.showHistory
                    ? 'text-blue-500'
                    : 'text-neutral-600 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-white'
                }`}
                title="Chat History"
              >
                <History size={16} />
              </button>
              <button
                onClick={live.handleCopyHistory}
                className="min-h-11 min-w-11 p-1.5 text-neutral-600 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-white transition-colors"
                title="Copy Raw Session Trace"
              >
                {live.copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
              </button>
            </div>
          </div>

          <LiveChatPanel {...livePanelProps} />
        </>
      ) : (
        <ExternalAiPanel {...externalPanelProps} />
      )}
      {live.pendingDelete && <ConfirmActionDialog title="Delete this conversation?"
        message={`Delete “${live.pendingDelete.title}” and its saved traces? This cannot be undone.`}
        actionLabel="Delete conversation" busy={owner.busyKind === 'history-delete'} error={owner.notice}
        onClose={() => live.setPendingDelete(null)} onConfirm={live.confirmDelete} />}
    </div>
  );
}
