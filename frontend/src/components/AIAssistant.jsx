import React, { useState, useEffect } from 'react';
import { Send, Settings, Sparkles, Loader2, Copy, Check, History, Trash, Plus } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useStore } from '../store';

const MessageRow = ({ m }) => {
  // Completely hide raw tool execution results from the UI to avoid clutter
  if (m.role === 'tool') return null;

  // Hide intermediate assistant messages that only contain tool calls and no textual content
  if (m.role === 'assistant' && !m.content && m.tool_calls) return null;
  
  // Hide Vision system auto-inject messages (where content is an array)
  if (m.role === 'user' && Array.isArray(m.content)) return null;

  const isUser = m.role === 'user';

  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} my-2`}>
      {m.content && typeof m.content === 'string' && (
        <div className={`p-3 rounded-lg max-w-[90%] text-sm shadow-sm ${isUser ? 'bg-blue-600 text-white' : 'bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100'}`}>
          {isUser ? (
             <div className="whitespace-pre-wrap">{m.content}</div>
          ) : (
             <ReactMarkdown className="markdown-body" remarkPlugins={[remarkGfm]}>
               {m.content}
             </ReactMarkdown>
          )}
        </div>
      )}
    </div>
  );
};

export default function AIAssistant() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi! I am the CatLabel AI Assistant. Tell me what kind of label you want to design, and I will generate it for you!' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [sessionUsage, setSessionUsage] = useState({ tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 });
  
  const [currentConvId, setCurrentConvId] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [histories, setHistories] = useState([]);

  const { items, canvasWidth, canvasHeight, isRotated, splitMode, canvasBorder, canvasBorderThickness, selectedPrinter, selectedPrinterInfo, batchRecords, printCopies, currentPage, currentDpi, setItems, setCanvasSize, setIsRotated, setSplitMode, setCanvasBorder, setCanvasBorderThickness, setCurrentPage } = useStore();
  const setShowAiConfig = useStore((state) => state.setShowAiConfig);

  useEffect(() => {
    fetchHistories();
  }, []);

  const fetchHistories = async () => {
    const res = await fetch('/api/ai/history');
    const data = await res.json();
    setHistories(data);
  };

  const handleCopyHistory = () => {
    const text = messages.map(m => {
        let out = `[${m.role.toUpperCase()}]\n`;
        if (m.content) out += `${m.content}\n`;
        if (m.tool_calls) {
            m.tool_calls.forEach(tc => {
                out += `> Tool Call: ${tc.function.name}(${tc.function.arguments})\n`;
            });
        }
        if (m.role === 'tool') {
            out += `> Tool Result: ${m.content}\n`;
        }
        return out;
    }).join('\n');
    
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const saveConversation = async (msgs, convId = currentConvId) => {
    try {
      if (convId) {
        await fetch(`/api/ai/history/${convId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: msgs })
        });
      } else {
        const title = msgs.length > 1 ? msgs[1].content.substring(0, 30) + '...' : 'New Conversation';
        const res = await fetch('/api/ai/history', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, messages: msgs })
        });
        const data = await res.json();
        setCurrentConvId(data.id);
        fetchHistories();
      }
    } catch (e) {
      console.error("Failed to save AI history", e);
    }
  };

  const loadHistory = async (id) => {
    const res = await fetch(`/api/ai/history/${id}`);
    const data = await res.json();
    setMessages(data.messages);
    setCurrentConvId(id);
    setShowHistory(false);
    setSessionUsage({ tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 });
  };

  const deleteHistory = async (id) => {
    await fetch(`/api/ai/history/${id}`, { method: 'DELETE' });
    if (currentConvId === id) setCurrentConvId(null);
    fetchHistories();
  };

  const handleSend = async () => {
    if (!input.trim()) return;
    const newMessages = [...messages, { role: 'user', content: input }];
    setMessages(newMessages);
    setInput('');
    setLoading(true);

    const currentState = {
      width: canvasWidth,
      height: canvasHeight,
      isRotated,
      splitMode,
      canvasBorder,
      canvasBorderThickness,
      items,
      currentPage,
      batchRecords,
      printCopies,
      __dpi__: currentDpi || selectedPrinterInfo?.dpi || 203
    };

    try {
      const b64Image = useStore.getState().getStageB64();

      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
           messages: newMessages, 
           canvas_state: currentState,
           mac_address: selectedPrinter || null,
           printer_info: selectedPrinterInfo || null,
           current_canvas_b64: b64Image ? b64Image.split(',')[1] : null
        })
      });
      
      const data = await res.json();
      
      if (data.error) {
        setMessages(prev =>[...prev, { role: 'assistant', content: `Error: ${data.error}` }]);
      } else if (data.new_messages) {
        const finalMessages = [...newMessages, ...data.new_messages];
        setMessages(finalMessages);
        saveConversation(finalMessages, currentConvId);

        if (data.usage) {
          setSessionUsage(prev => ({
            tokens: prev.tokens + (data.usage.total_tokens || 0),
            promptTokens: (prev.promptTokens || 0) + (data.usage.prompt_tokens || 0),
            completionTokens: (prev.completionTokens || 0) + (data.usage.completion_tokens || 0),
            cost: prev.cost + (data.usage.cost || 0)
          }));
        }
        
        if (data.canvas_state) {
            setItems(data.canvas_state.items ||[]);
            if (data.canvas_state.width && data.canvas_state.height) {
                setCanvasSize(data.canvas_state.width, data.canvas_state.height);
            }
            if (data.canvas_state.isRotated !== undefined) setIsRotated(data.canvas_state.isRotated);
            if (data.canvas_state.splitMode !== undefined) setSplitMode(data.canvas_state.splitMode);
            if (data.canvas_state.canvasBorder !== undefined) setCanvasBorder(data.canvas_state.canvasBorder);
            if (data.canvas_state.canvasBorderThickness !== undefined) setCanvasBorderThickness(data.canvas_state.canvasBorderThickness);
            if (data.canvas_state.batchRecords) useStore.getState().setBatchRecords(data.canvas_state.batchRecords);
            if (data.canvas_state.printCopies !== undefined) useStore.getState().setPrintCopies(data.canvas_state.printCopies);
            if (data.canvas_state.currentPage !== undefined) setCurrentPage(data.canvas_state.currentPage);
            
            // Execute intercepted UI actions from the agent
            if (data.canvas_state.__actions__) {
                data.canvas_state.__actions__.forEach(action => {
                    if (action.action === 'print') {
                        const actionItems = data.canvas_state.items || [];
                        const maxPage = actionItems.reduce(
                            (max, item) => Math.max(max, Number(item.pageIndex ?? 0)),
                            0
                        );
                        const allPageIndices = Array.from({ length: maxPage + 1 }, (_, i) => i);
                        useStore.getState().printPages(allPageIndices);
                    } 
                    else if (action.action === 'refresh_projects') {
                        useStore.getState().fetchProjects();
                    } 
                    else if (action.action === 'loaded_project_id') {
                        useStore.getState().setCurrentProjectId(action.project_id);
                    }
                });
            }
        }
      }
    } catch (err) {
      setMessages(prev =>[...prev, { role: 'assistant', content: 'Failed to connect to the AI Agent.' }]);
    }
    setLoading(false);
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-neutral-950">
      {/* Inline styles for markdown to keep it zero-config */}
      <style dangerouslySetInnerHTML={{__html: `
        .markdown-body p { margin-bottom: 0.75rem; }
        .markdown-body p:last-child { margin-bottom: 0; }
        .markdown-body ul { list-style-type: disc; padding-left: 1.5rem; margin-bottom: 0.75rem; }
        .markdown-body ol { list-style-type: decimal; padding-left: 1.5rem; margin-bottom: 0.75rem; }
        .markdown-body code { background-color: rgba(150,150,150,0.15); padding: 0.2rem 0.4rem; border-radius: 0.25rem; font-family: monospace; font-size: 0.9em; }
        .markdown-body pre { background-color: rgba(0,0,0,0.8); color: white; padding: 0.75rem; border-radius: 0.375rem; overflow-x: auto; margin-bottom: 0.75rem; font-family: monospace; }
        .markdown-body h1, .markdown-body h2, .markdown-body h3, .markdown-body h4 { font-weight: 700; margin-bottom: 0.5rem; margin-top: 1rem; }
        .markdown-body a { color: #3b82f6; text-decoration: underline; }
        .markdown-body strong { font-weight: 700; }
      `}} />

      <div className="flex items-center justify-between pb-3 border-b border-neutral-100 dark:border-neutral-800">
        <h2 className="flex items-center gap-2 text-lg font-serif tracking-tight text-neutral-900 dark:text-white">
          <Sparkles size={18} className="text-blue-500" /> AI Assistant
        </h2>
        <div className="flex gap-1">
          <button onClick={() => setShowHistory(!showHistory)} className={`p-1.5 transition-colors ${showHistory ? 'text-blue-500' : 'text-neutral-400 hover:text-neutral-900 dark:hover:text-white'}`} title="Chat History">
            <History size={16} />
          </button>
          <button onClick={handleCopyHistory} className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors" title="Copy Chat History">
            {copied ? <Check size={16} className="text-green-500"/> : <Copy size={16} />}
          </button>
          <button onClick={() => setShowAiConfig(true)} className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors" title="AI Settings">
            <Settings size={16} />
          </button>
        </div>
      </div>

      {showHistory ? (
        <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col">
          <button onClick={() => { setMessages([{ role: 'assistant', content: 'Hi! Tell me what kind of label you want to design.' }]); setCurrentConvId(null); setShowHistory(false); setSessionUsage({ tokens: 0, promptTokens: 0, completionTokens: 0, cost: 0 }); }} className="mb-4 text-blue-500 font-bold text-xs uppercase tracking-widest flex items-center gap-2 px-3 py-2 border border-blue-200 dark:border-blue-900/50 bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/40 rounded transition-colors">
            <Plus size={16} /> Start New Conversation
          </button>
          {histories.map(h => (
            <div key={h.id} className="flex items-center justify-between p-3 border border-neutral-200 dark:border-neutral-800 mb-2 rounded cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-900 transition-colors" onClick={() => loadHistory(h.id)}>
              <div className="text-sm font-medium truncate flex-1 dark:text-white pr-4">{h.title}</div>
              <button onClick={(e) => { e.stopPropagation(); deleteHistory(h.id); }} className="text-neutral-400 hover:text-red-500 transition-colors">
                <Trash size={14} />
              </button>
            </div>
          ))}
          {histories.length === 0 && <div className="text-xs text-neutral-500 text-center mt-10">No saved conversations yet.</div>}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col">
          {messages.map((m, i) => (
            <MessageRow key={i} m={m} />
          ))}
          {loading && (
            <div className="flex justify-start my-2">
              <div className="p-3 rounded-lg bg-neutral-100 dark:bg-neutral-900 text-neutral-500 flex items-center gap-2 text-sm">
                <Loader2 size={14} className="animate-spin text-blue-500" /> Thinking &amp; Executing Tools...
              </div>
            </div>
          )}
        </div>
      )}

      <div className="pt-3 border-t border-neutral-100 dark:border-neutral-800 mt-auto">
        <form onSubmit={e => { e.preventDefault(); handleSend(); }} className="flex gap-2">
          <input 
            type="text" 
            value={input} 
            onChange={e => setInput(e.target.value)} 
            disabled={loading}
            placeholder="Ask AI to design a label..." 
            className="flex-1 bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 transition-colors"
          />
          <button type="submit" disabled={loading || !input.trim()} className="bg-blue-600 text-white p-2 hover:bg-blue-700 transition-colors disabled:opacity-50">
            <Send size={18} />
          </button>
        </form>
        {sessionUsage.tokens > 0 && (
          <div className="flex justify-between items-center mt-2 px-1 text-[10px] uppercase tracking-widest font-bold text-neutral-400 dark:text-neutral-500">
            <span title={`Prompt: ${sessionUsage.promptTokens.toLocaleString()} | Completion: ${sessionUsage.completionTokens.toLocaleString()}`}>
              Session Tokens: {sessionUsage.tokens.toLocaleString()}
            </span>
            <span title="Estimated API cost based on LiteLLM pricing">
              Cost: {sessionUsage.cost > 0 ? `$${sessionUsage.cost.toFixed(4)}` : 'Unknown / Free'}
            </span>
          </div>
        )}
      </div>

    </div>
  );
}
