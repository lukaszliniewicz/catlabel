import React, { useState } from 'react';
import { X, Calendar } from 'lucide-react';
import { useStore } from '../store';

export default function DateToolModal({ onClose }) {
  const { addItem, canvasWidth, settings } = useStore();
  const [mode, setMode] = useState('today');
  const [offsetDays, setOffsetDays] = useState(1);
  const [customDate, setCustomDate] = useState('');
  const [format, setFormat] = useState('YYYY-MM-DD');

  const generateDateString = () => {
    let targetDate = new Date();
    if (mode === 'offset') {
      targetDate.setDate(targetDate.getDate() + parseInt(offsetDays, 10));
    } else if (mode === 'custom' && customDate) {
      targetDate = new Date(customDate);
    }

    const yyyy = targetDate.getFullYear();
    const mm = String(targetDate.getMonth() + 1).padStart(2, '0');
    const dd = String(targetDate.getDate()).padStart(2, '0');

    if (format === 'YYYY-MM-DD') return `${yyyy}-${mm}-${dd}`;
    if (format === 'DD/MM/YYYY') return `${dd}/${mm}/${yyyy}`;
    if (format === 'MM/DD/YYYY') return `${mm}/${dd}/${yyyy}`;
    return targetDate.toDateString();
  };

  const handleAdd = () => {
    const dateText = generateDateString();
    const defaultFont = settings.default_font || 'RobotoCondensed.ttf';
    
    addItem({
      id: Date.now().toString(),
      type: 'text',
      text: dateText,
      x: 0,
      y: 50,
      size: 32,
      weight: 700,
      font: defaultFont,
      width: canvasWidth,
      align: 'center'
    });
    onClose();
  };

  const btnClass = (active) => `flex-1 py-2 text-[10px] font-bold uppercase transition-colors border ${active ? 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/30 dark:border-blue-800' : 'bg-neutral-50 text-neutral-500 border-transparent hover:bg-neutral-100 dark:bg-neutral-900 dark:hover:bg-neutral-800'}`;

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-sm rounded-xl shadow-2xl flex flex-col border border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <div className="flex items-center gap-2">
            <Calendar className="text-blue-500" size={20} />
            <h3 className="font-serif text-lg dark:text-white">Insert Date</h3>
          </div>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div className="flex gap-2">
            <button onClick={() => setMode('today')} className={btnClass(mode === 'today')}>Today</button>
            <button onClick={() => setMode('offset')} className={btnClass(mode === 'offset')}>+ Offset</button>
            <button onClick={() => setMode('custom')} className={btnClass(mode === 'custom')}>Custom</button>
          </div>

          {mode === 'offset' && (
            <div>
              <label className="block text-[10px] font-bold text-neutral-400 uppercase mb-1">Add Days</label>
              <input type="number" value={offsetDays} onChange={e => setOffsetDays(e.target.value)} className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500" />
            </div>
          )}

          {mode === 'custom' && (
            <div>
              <label className="block text-[10px] font-bold text-neutral-400 uppercase mb-1">Select Date</label>
              <input type="date" value={customDate} onChange={e => setCustomDate(e.target.value)} className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 [color-scheme:light] dark:[color-scheme:dark]" />
            </div>
          )}

          <div>
            <label className="block text-[10px] font-bold text-neutral-400 uppercase mb-1">Format</label>
            <select value={format} onChange={e => setFormat(e.target.value)} className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500">
              <option value="YYYY-MM-DD">YYYY-MM-DD</option>
              <option value="DD/MM/YYYY">DD/MM/YYYY</option>
              <option value="MM/DD/YYYY">MM/DD/YYYY</option>
            </select>
          </div>
          
          <div className="pt-2">
             <p className="text-center text-xs text-neutral-500">Preview: <strong className="text-neutral-900 dark:text-white">{generateDateString()}</strong></p>
          </div>
        </div>

        <div className="p-4 border-t border-neutral-100 dark:border-neutral-800">
          <button onClick={handleAdd} className="w-full bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold">
            Add to Canvas
          </button>
        </div>
      </div>
    </div>
  );
}
