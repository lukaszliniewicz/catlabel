import React, { useState } from 'react';
import { X, Save, Bookmark } from 'lucide-react';
import { useStore } from '../store';

export default function ShippingLabelModal({ onClose }) {
  const { addresses, saveAddress, deleteAddress, isRotated, setIsRotated, canvasWidth, canvasHeight, setCanvasSize, setItems, clearCanvas } = useStore();

  const [fromLabel, setFromLabel] = useState('Sender');
  const [fromData, setFromData] = useState({ name: '', street: '', zip: '', city: '', country: '' });

  const [toLabel, setToLabel] = useState('Recipient');
  const [toData, setToData] = useState({ name: '', street: '', zip: '', city: '', country: '' });

  const handleSaveAddress = (data) => {
    const alias = prompt("Enter a memorable name for this address (e.g. 'Home', 'Office'):");
    if (alias) {
      saveAddress({ alias, ...data });
    }
  };

  const handleLoadAddress = (e, setFn) => {
    const addr = addresses.find(a => a.id === parseInt(e.e.target.value));
    if (addr) {
      setFn({ name: addr.name, street: addr.street, zip: addr.zip, city: addr.city, country: addr.country });
    }
  };

  const handleGenerate = () => {
    // Usually thermal profiles report width at 384. A standard label needs Landscape orientation (~576px depth).
    const targetW = Math.max(canvasWidth, canvasHeight, 576); 
    const targetH = Math.min(canvasWidth, canvasHeight, 384);
    
    if (!isRotated) setIsRotated(true);
    setCanvasSize(targetW, targetH);
    
    const newItems = [];
    const timestamp = Date.now().toString();
    
    const fLines = [fromData.name, fromData.street, `${fromData.zip} ${fromData.city}`.trim(), fromData.country].filter(Boolean);
    const tLines = [toData.name, toData.street, `${toData.zip} ${toData.city}`.trim(), toData.country].filter(Boolean);

    // 1. Sender Label / Header
    newItems.push({
      id: `${timestamp}-flbl`, type: 'text', text: ` ${fromLabel} `, x: 16, y: 24, size: 14, font: 'arial.ttf',
      width: 120, align: 'center', invert: true, no_wrap: true, bg_white: false
    });
    
    // 2. Sender Details
    newItems.push({
      id: `${timestamp}-fdet`, type: 'text', text: fLines.join('\n'), x: 16, y: 56, size: 18, font: 'arial.ttf',
      width: 250, align: 'left', no_wrap: false, invert: false, bg_white: false
    });
    
    // 3. Separator Line
    newItems.push({
      id: `${timestamp}-line`, type: 'cut_line_indicator', isVertical: true, x: targetW * 0.45, y: 16, width: 1, height: targetH - 32
    });

    // 4. Recipient Label / Header
    newItems.push({
      id: `${timestamp}-tlbl`, type: 'text', text: ` ${toLabel} `, x: targetW * 0.5, y: targetH * 0.2, size: 18, font: 'arial.ttf',
      width: 150, align: 'center', invert: true, no_wrap: true, bg_white: false
    });

    // 5. Recipient Details (Much larger)
    newItems.push({
      id: `${timestamp}-tdet`, type: 'text', text: tLines.join('\n'), x: targetW * 0.5, y: targetH * 0.2 + 40, size: 30, font: 'arial.ttf',
      width: targetW * 0.45, align: 'left', no_wrap: false, invert: false, bg_white: false
    });

    clearCanvas();
    setItems(newItems);
    onClose();
  };

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 mb-3 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1";

  const AddressForm = ({ label, setLabel, data, setData }) => (
    <div className="flex-1 border border-neutral-200 dark:border-neutral-800 p-4 bg-neutral-50 dark:bg-neutral-900/50 rounded-sm">
      <div className="flex items-center gap-2 mb-4 pb-4 border-b border-neutral-200 dark:border-neutral-800">
        <input 
          value={label} onChange={e => setLabel(e.target.value)}
          className="text-lg font-serif bg-transparent border-b border-transparent focus:border-blue-500 outline-none w-1/2 dark:text-white"
          title="Editable Heading Label"
        />
        
        <select 
          className="w-1/2 bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-700 p-2 text-xs uppercase tracking-wider text-neutral-900 dark:text-white focus:outline-none focus:border-blue-500"
          onChange={e => {
            const addr = addresses.find(a => a.id === parseInt(e.target.value));
            if (addr) setData({ name: addr.name, street: addr.street, zip: addr.zip, city: addr.city, country: addr.country });
            e.target.value = "";
          }}
          defaultValue=""
        >
          <option value="" disabled>Load from book...</option>
          {addresses.map(a => <option key={a.id} value={a.id}>{a.alias} - {a.name}</option>)}
        </select>
      </div>

      <div>
        <label className={labelClass}>Full Name</label>
        <input type="text" value={data.name} onChange={e => setData({...data, name: e.target.value})} className={inputClass} />
        
        <label className={labelClass}>Street & House No.</label>
        <input type="text" value={data.street} onChange={e => setData({...data, street: e.target.value})} className={inputClass} />
        
        <div className="flex gap-4">
          <div className="w-1/3">
            <label className={labelClass}>ZIP</label>
            <input type="text" value={data.zip} onChange={e => setData({...data, zip: e.target.value})} className={inputClass} />
          </div>
          <div className="w-2/3">
            <label className={labelClass}>City</label>
            <input type="text" value={data.city} onChange={e => setData({...data, city: e.target.value})} className={inputClass} />
          </div>
        </div>

        <label className={labelClass}>Country</label>
        <input type="text" value={data.country} onChange={e => setData({...data, country: e.target.value})} className={inputClass} />
      </div>

      <button 
        onClick={() => handleSaveAddress(data)}
        className="flex items-center gap-2 mt-2 text-xs uppercase tracking-widest font-bold text-neutral-500 hover:text-blue-600 transition-colors"
      >
        <Bookmark size={14} /> Save to Address Book
      </button>
    </div>
  );

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-4xl rounded-xl shadow-2xl flex flex-col max-h-[90vh] border border-neutral-200 dark:border-neutral-800">
        
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-xl dark:text-white tracking-tight">Shipping Label Wizard</h3>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1 flex flex-col md:flex-row gap-6">
          <AddressForm label={fromLabel} setLabel={setFromLabel} data={fromData} setData={setFromData} />
          <AddressForm label={toLabel} setLabel={setToLabel} data={toData} setData={setToData} />
        </div>

        <div className="p-4 border-t border-neutral-100 dark:border-neutral-800 mt-auto">
          <button 
            onClick={handleGenerate}
            className="w-full bg-blue-600 text-white px-4 py-3 hover:bg-blue-700 transition-colors text-xs uppercase tracking-widest font-bold flex justify-center items-center gap-2"
          >
            <Save size={16} /> Generate & Replace Canvas Layout
          </button>
        </div>

      </div>
    </div>
  );
}
