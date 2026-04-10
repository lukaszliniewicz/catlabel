import React, { useState } from 'react';
import { Send, Settings, Sparkles, Loader2 } from 'lucide-react';
import AIConfigModal from './AIConfigModal';
import { useStore } from '../store';

export default function AIAssistant() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi! I am the TiMini Print AI Assistant. Tell me what kind of label you want to design, and I will generate it for you!' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showConfig, setShowConfig] = useState(false);

  // Add canvasBorderThickness and selectedPrinter from Zustand to power the print command
  const { items, canvasWidth, canvasHeight, isRotated, splitMode, canvasBorder, canvasBorderThickness, selectedPrinter, setItems, setCanvasSize, setIsRotated, setSplitMode, setCanvasBorder } = useStore();

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
        setMessages([...newMessages, { role: 'assistant', content: `Error: ${data.error}` }]);
      } else {
        setMessages([...newMessages, { role: 'assistant', content: data.message }]);
        
        // Apply returned canvas state modifications silently
        if (data.canvas_state) {
            setItems(data.canvas_state.items || []);
            if (data.canvas_state.width && data.canvas_state.height) {
                setCanvasSize(data.canvas_state.width, data.canvas_state.height);
            }
            if (data.canvas_state.isRotated !== undefined) setIsRotated(data.canvas_state.isRotated);
            if (data.canvas_state.splitMode !== undefined) setSplitMode(data.canvas_state.splitMode);
            if (data.canvas_state.canvasBorder !== undefined) setCanvasBorder(data.canvas_state.canvasBorder);
            
            // NEW: Execute intercepted UI actions from the agent
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
      setMessages([...newMessages, { role: 'assistant', content: 'Failed to connect to the AI Agent.' }]);
    }
    setLoading(false);
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-neutral-950">
      <div className="flex items-center justify-between pb-3 border-b border-neutral-100 dark:border-neutral-800">
        <h2 className="flex items-center gap-2 text-lg font-serif tracking-tight text-neutral-900 dark:text-white">
          <Sparkles size={18} className="text-blue-500" /> AI Assistant
        </h2>
        <button onClick={() => setShowConfig(true)} className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-white transition-colors" title="AI Settings">
          <Settings size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-4 space-y-4 pr-2">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`p-3 rounded-lg max-w-[85%] text-sm shadow-sm ${m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100'}`}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="p-3 rounded-lg bg-neutral-100 dark:bg-neutral-900 text-neutral-500 flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" /> Thinking & Using Tools...
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
