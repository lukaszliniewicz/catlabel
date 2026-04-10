import React, { useState } from 'react';
import { Send, Settings, Sparkles, Loader2, Copy, Check } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import AIConfigModal from './AIConfigModal';
import { useStore } from '../store';

const MessageRow = ({ m }) => {
  // Hide raw tool execution results from the UI to avoid clutter, 
  // but keep them in state so the LLM has context.
  if (m.role === 'tool') {
    return (
      <div className="flex justify-center my-1">
        <div className="text-[9px] uppercase tracking-widest font-bold bg-neutral-100 dark:bg-neutral-800 text-neutral-400 py-1 px-3 rounded-full flex items-center gap-1">
          ✅ Tool Executed: {m.name}
        </div>
      </div>
    );
  }

  const isUser = m.role === 'user';

  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} my-2`}>
      {m.content && (
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
      
      {/* Render AI Tool Call Indicators natively */}
      {m.tool_calls && m.tool_calls.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5 items-start max-w-[90%]">
          {m.tool_calls.map(tc => (
            <div key={tc.id} className="text-xs bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 py-1.5 px-3 rounded-lg border border-blue-100 dark:border-blue-800/50 font-mono flex flex-col gap-1 shadow-sm">
              <div className="flex items-center gap-2 font-bold">
                <Sparkles size={12} />
                <span>{tc.function.name}</span>
              </div>
              <div className="text-[10px] opacity-75 truncate max-w-xs" title={tc.function.arguments}>
                {tc.function.arguments}
              </div>
            </div>
          ))}
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
  const [showConfig, setShowConfig] = useState(false);
  const [copied, setCopied] = useState(false);

  const { items, canvasWidth, canvasHeight, isRotated, splitMode, canvasBorder, canvasBorderThickness, selectedPrinter, setItems, setCanvasSize, setIsRotated, setSplitMode, setCanvasBorder } = useStore();

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

  const handleSend = async () => {
    if (!input.trim()) return;
    const newMessages = [...messages, { role: 'user', content: input }];
    setMessages(newMessages);
    setInput('');
    setLoading(true);

    const currentState = {
      width: canvasWidth, height: canvasHeight, isRotated, splitMode, canvasBorder, items
    };

    try {
      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
           messages: newMessages, 
           canvas_state: currentState,
           mac_address: selectedPrinter || null
        })
      });
      
      const data = await res.json();
      
      if (data.error) {
        setMessages(prev =>[...prev, { role: 'assistant', content: `Error: ${data.error}` }]);
      } else if (data.new_messages) {
        // Correctly append all intermediate tool calls and the final response
        setMessages(prev =>[...prev, ...data.new_messages]);
        
        if (data.canvas_state) {
            setItems(data.canvas_state.items ||[]);
            if (data.canvas_state.width && data.canvas_state.height) {
                setCanvasSize(data.canvas_state.width, data.canvas_state.height);
            }
            if (data.canvas_state.isRotated !== undefined) setIsRotated(data.canvas_state.isRotated);
            if (data.canvas_state.splitMode !== undefined) setSplitMode(data.canvas_state.splitMode);
            if (data.canvas_state.canvasBorder !== undefined) setCanvasBorder(data.canvas_state.canvasBorder);
            
            // Execute intercepted UI actions from the agent
            if (data.canvas_state.__actions__) {
                data.canvas_state.__actions__.forEach(action => {
                    if (action.action === 'print') {
                        if (!selectedPrinter) {
                            alert("The AI attempted to print, but no printer is currently selected!");
                            return;
                        }
                        const thickness = canvasBorderThickness || 4;
                        fetch('/api/print/direct', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                mac_address: selectedPrinter,
                                canvas_state: { ...data.canvas_state, canvasBorderThickness: thickness },
                                variables: {}
                            })
                        }).then(r => r.json()).then(resp => {
                            if (resp.error || resp.detail) alert(`AI Print Failed: ${resp.error || resp.detail}`);
                        });
                    } else if (action.action === 'save_project') {
                        fetch('/api/projects', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                name: action.project_name || "AI Generated Project",
                                canvas_state: data.canvas_state
                            })
                        }).then(() => {
                            useStore.getState().fetchProjects();
                        });
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
          <button onClick={handleCopyHistory} className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors" title="Copy Chat History">
            {copied ? <Check size={16} className="text-green-500"/> : <Copy size={16} />}
          </button>
          <button onClick={() => setShowConfig(true)} className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors" title="AI Settings">
            <Settings size={16} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col">
        {messages.map((m, i) => (
          <MessageRow key={i} m={m} />
        ))}
        {loading && (
          <div className="flex justify-start my-2">
            <div className="p-3 rounded-lg bg-neutral-100 dark:bg-neutral-900 text-neutral-500 flex items-center gap-2 text-sm">
              <Loader2 size={14} className="animate-spin text-blue-500" /> Thinking & Executing Tools...
            </div>
          </div>
        )}
      </div>

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
      </div>

      {showConfig && <AIConfigModal onClose={() => setShowConfig(false)} />}
    </div>
  );
}
