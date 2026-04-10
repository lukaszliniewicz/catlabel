import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Save, Bookmark } from 'lucide-react';
import { useStore } from '../store';

export default function ShippingLabelModal({ onClose }) {
  const { addresses, saveAddress, isRotated, setIsRotated, canvasWidth, canvasHeight, setCanvasSize, setItems, clearCanvas } = useStore();

  const [fromLabel, setFromLabel] = useState('Sender');
  const [fromData, setFromData] = useState({ name: '', street: '', zip: '', city: '', country: '' });

  const [toLabel, setToLabel] = useState('Recipient');
  const [toData, setToData] = useState({ name: '', street: '', zip: '', city: '', country: '' });

  const [customText, setCustomText] = useState('');

  const handleSaveAddress = (data) => {
    const alias = prompt("Enter a memorable name for this address (e.g. 'Home', 'Office'):");
    if (alias) {
      saveAddress({ alias, ...data });
    }
  };

  const handleGenerate = () => {
    // Thermal profiles usually report width at 384. A standard label needs Landscape orientation (~576px+ depth).
    const targetW = Math.max(canvasWidth, canvasHeight, 576); 
    const targetH = Math.min(canvasWidth, canvasHeight, 384);
    
    if (!isRotated) setIsRotated(true);
    setCanvasSize(targetW, targetH);
    
    const newItems = [];
    const timestamp = Date.now().toString();
    
    const fLines = [fromData.name, fromData.street, `${fromData.zip} ${fromData.city}`.trim(), fromData.country].filter(Boolean);
    const tLines = [toData.street, `${toData.zip} ${toData.city}`.trim(), toData.country].filter(Boolean);

    // 1. Sender Details (Top Left, compact text size)
    newItems.push({
      id: `${timestamp}-fdet`, type: 'text', 
      text: `FROM:\n${fLines.join('\n')}`, 
      x: 16, y: 16, size: 16, font: 'arial.ttf',
      width: targetW * 0.45, align: 'left', no_wrap: false
    });
    
    // 2. Bold Horizontal Divider
    newItems.push({
      id: `${timestamp}-line1`, type: 'text', text: '', 
      x: 0, y: 110, width: targetW, size: 2, border_style: 'top', border_thickness: 4
    });

    const hasCustomText = customText.trim().length > 0;

    // 3. Inverted "SHIP TO:" Label pop-out
    newItems.push({
      id: `${timestamp}-tlbl`, type: 'text', 
      text: `SHIP TO:`, 
      x: 16, y: 130, size: 20, font: 'arial.ttf',
      width: 100, align: 'center', no_wrap: true, invert: true, border_style: 'box'
    });

    // 4. Auto-Sized huge Recipient Name
    newItems.push({
      id: `${timestamp}-tname`, type: 'text', 
      text: toData.name || 'Recipient Name', 
      x: 16, y: 170, size: 60, font: 'arial.ttf',
      width: targetW - 32, align: 'left', no_wrap: true, fit_to_width: true
    });

    // 5. Large Address Body underneath
    newItems.push({
      id: `${timestamp}-tdet`, type: 'text', 
      text: tLines.join('\n'), 
      x: 16, y: 240, size: 32, font: 'arial.ttf',
      width: targetW - 32, align: 'left', no_wrap: false
    });

    // 6. Optional Custom Text Bar
    if (hasCustomText) {
      newItems.push({
        id: `${timestamp}-line2`, type: 'text', text: '', 
        x: 0, y: targetH - 40, width: targetW, size: 2, border_style: 'top', border_thickness: 4
      });
      newItems.push({
        id: `${timestamp}-custom`, type: 'text', 
        text: customText.trim(), 
        x: 16, y: targetH - 32, size: 20, font: 'arial.ttf',
        width: targetW - 32, align: 'center', no_wrap: true, fit_to_width: true
      });
    }

    clearCanvas();
    setItems(newItems);
    onClose();
  };

  const inputClass = "w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-2 text-sm dark:text-white focus:outline-none focus:border-blue-500 mb-3 transition-colors";
  const labelClass = "block text-[10px] font-bold text-neutral-400 uppercase tracking-widest mb-1";

  const AddressForm = ({ label, setLabel, data, setData, type }) => {
    // Determine the autocomplete prefix based on the context to aid browser autofill heavily
    const prefix = type === 'to' ? 'shipping ' : '';
    
    return (
      <form className="flex-1 border border-neutral-200 dark:border-neutral-800 p-4 bg-neutral-50 dark:bg-neutral-900/50 rounded-sm" onSubmit={e => e.preventDefault()}>
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
          <input type="text" name={`${type}-name`} autoComplete={`${prefix}name`} value={data.name} onChange={e => setData({...data, name: e.target.value})} className={inputClass} />
          
          <label className={labelClass}>Street & House No.</label>
          <input type="text" name={`${type}-street`} autoComplete={`${prefix}street-address`} value={data.street} onChange={e => setData({...data, street: e.target.value})} className={inputClass} />
          
          <div className="flex gap-4">
            <div className="w-1/3">
              <label className={labelClass}>ZIP</label>
              <input type="text" name={`${type}-zip`} autoComplete={`${prefix}postal-code`} value={data.zip} onChange={e => setData({...data, zip: e.target.value})} className={inputClass} />
            </div>
            <div className="w-2/3">
              <label className={labelClass}>City</label>
              <input type="text" name={`${type}-city`} autoComplete={`${prefix}address-level2`} value={data.city} onChange={e => setData({...data, city: e.target.value})} className={inputClass} />
            </div>
          </div>

          <label className={labelClass}>Country</label>
          <input type="text" name={`${type}-country`} autoComplete={`${prefix}country-name`} value={data.country} onChange={e => setData({...data, country: e.target.value})} className={inputClass} />
        </div>

        <button 
          type="button"
          onClick={() => handleSaveAddress(data)}
          className="flex items-center gap-2 mt-2 text-xs uppercase tracking-widest font-bold text-neutral-500 hover:text-blue-600 transition-colors"
        >
          <Bookmark size={14} /> Save to Address Book
        </button>
      </form>
    );
  };

  const modalContent = (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-950 w-full max-w-4xl rounded-xl shadow-2xl flex flex-col max-h-[90vh] border border-neutral-200 dark:border-neutral-800">
        
        <div className="flex items-center justify-between p-4 border-b border-neutral-100 dark:border-neutral-800">
          <h3 className="font-serif text-xl dark:text-white tracking-tight">Shipping Label Wizard</h3>
          <button onClick={onClose} className="p-2 text-neutral-500 hover:text-neutral-900 dark:hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-6">
          <div className="flex flex-col md:flex-row gap-6">
            <AddressForm label={fromLabel} setLabel={setFromLabel} data={fromData} setData={setFromData} type="from" />
            <AddressForm label={toLabel} setLabel={setToLabel} data={toData} setData={setToData} type="to" />
          </div>
          
          <div className="border border-neutral-200 dark:border-neutral-800 p-4 bg-neutral-50 dark:bg-neutral-900/50 rounded-sm">
            <label className={labelClass}>Optional Reference / Custom Text (Printed at bottom)</label>
            <input 
              type="text" 
              value={customText} 
              onChange={e => setCustomText(e.target.value)} 
              className={inputClass.replace('mb-3', 'mb-0')} 
              placeholder="e.g. Fragile, Order #12345, Keep Dry" 
            />
          </div>
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

  return createPortal(modalContent, document.body);
}
