import React, { useId, useState } from 'react';
import { useStore } from '../../store';
import { useShallow } from 'zustand/react/shallow';
import { AlignCenter, MoveHorizontal, Maximize2, Plus, Bold, Italic, Underline } from 'lucide-react';
import { MmScrubberInput, ScrubberInput } from '../NumericInput';
import { calculateAutoFitItem } from '../../utils/rendering';
import { inputClass, labelClass } from './styles';
import FileUploadButton from '../FileUploadButton';
import LazyFeature from '../LazyFeature';
const IconPicker = React.lazy(() => import('../IconPicker'));

const ToggleBtn = ({ icon: Icon, active, onClick, label }) => (
  <button
    onClick={onClick}
    title={label}
    aria-label={label}
    aria-pressed={active}
    className={`flex-1 flex justify-center items-center py-1.5 transition-colors rounded-xs ${
      active
        ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-900 dark:text-white shadow-inner'
        : 'bg-transparent text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800'
    }`}
  >
    <Icon size={16} />
  </button>
);

export default function ElementSettings({ selectedItem, dupCopies, setDupCopies, dupGap, setDupGap, handleFormatHtml }) {
  const selectedId = selectedItem.id;
  const tabId = useId();
  const { updateItem, deleteItem, canvasWidth, canvasHeight, batchRecords, settings, fonts, uploadFont } = useStore(useShallow(state => ({
    updateItem: state.updateItem, deleteItem: state.deleteItem, canvasWidth: state.canvasWidth,
    canvasHeight: state.canvasHeight, batchRecords: state.batchRecords, settings: state.settings, fonts: state.fonts, uploadFont: state.uploadFont
  })));
  const [showIconPicker, setShowIconPicker] = useState(false);
  const handleCenterAbsolute = () => {
    if (!selectedItem) return;
    const itemW = selectedItem.width || 0;

    let itemH = selectedItem.height || 0;
    if (!itemH && selectedItem.type === 'text') {
      const pad = selectedItem.padding !== undefined ? Number(selectedItem.padding) : ((selectedItem.invert || selectedItem.bg_white) ? 4 : 0);
      const numLines = selectedItem.text ? String(selectedItem.text).split('\n').length : 1;
      const actualLineHeight = selectedItem.lineHeight ?? (numLines > 1 ? 1.15 : 1);
      itemH = (selectedItem.size * actualLineHeight * numLines) + (pad * 2);
    }

    updateItem(selectedId, {
      x: (canvasWidth - itemW) / 2,
      y: (canvasHeight - itemH) / 2
    });
  };

  const handleMakeFullWidth = () => {
    if (!selectedItem) return;
    if (selectedItem.type === 'group') {
      useStore.getState().fitGroupToWidth();
      return;
    }

    let newHeight = selectedItem.height;

    if (selectedItem.type === 'qrcode') {
      newHeight = canvasWidth;
    } else if (selectedItem.type === 'image' && selectedItem.width && selectedItem.height) {
      const ratio = selectedItem.width / selectedItem.height;
      newHeight = Math.round(canvasWidth / ratio);
    }

    updateItem(selectedId, {
      x: 0,
      width: canvasWidth,
      height: newHeight,
      align: 'center'
    });
  };

  const handleFitToWidth = () => {
    if (!selectedItem || !selectedItem.text) return;

    const optimized = calculateAutoFitItem(
      { ...selectedItem, fit_to_width: true },
      batchRecords,
      canvasWidth,
      canvasHeight
    );

    updateItem(selectedId, {
      size: optimized.size,
      fit_to_width: true
    });
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    let parsedValue = type === 'checkbox' ? checked : (type === 'number' ? Number(value) : value);

    if (selectedItem.type === 'image' && (name === 'width' || name === 'height')) {
      const ratio = selectedItem.width / selectedItem.height;
      if (name === 'width') {
        updateItem(selectedId, { width: parsedValue, height: Math.round(parsedValue / ratio) });
      } else {
        updateItem(selectedId, { height: parsedValue, width: Math.round(parsedValue * ratio) });
      }
      return;
    }
    updateItem(selectedId, { [name]: parsedValue });
  };

  return <>
            <div className="space-y-4">
              <div>
                <div className="grid grid-cols-3 gap-2">
                  <MmScrubberInput name="x" label="X Pos" value={selectedItem.x} onChange={handleChange} />
                  <MmScrubberInput name="y" label="Y Pos" value={selectedItem.y} onChange={handleChange} />
                  <ScrubberInput name="rotation" label="Rot(°)" value={Math.round(selectedItem.rotation || 0)} onChange={handleChange} />
                </div>

                <div className="flex gap-2 mt-3">
                  <button onClick={handleCenterAbsolute} title="Center Absolutely" aria-label="Center element on canvas" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                    <AlignCenter size={16} />
                  </button>
                  <button onClick={handleMakeFullWidth} title="Full Width" aria-label="Fit element to canvas width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                    <MoveHorizontal size={16} />
                  </button>
                  {selectedItem.type === 'text' && (
                    <button onClick={handleFitToWidth} title="Maximize Font to Width" aria-label="Maximize font to width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                      <Maximize2 size={16} />
                    </button>
                  )}
                </div>
              </div>

              {selectedItem.type === 'text' && (
                <>
                  <div>
                    <label className={labelClass} htmlFor={`${tabId}-text`}>Text Content</label>
                    <textarea id={`${tabId}-text`} name="text" value={selectedItem.text} onChange={handleChange} className={inputClass} rows={3} />
                  </div>

                  <div className="flex gap-2 mt-2 border border-neutral-200 dark:border-neutral-800 rounded-sm p-1 bg-neutral-50 dark:bg-neutral-900/50">
                    <ToggleBtn icon={Bold} label="Bold" active={selectedItem.weight >= 700} onClick={() => updateItem(selectedId, { weight: selectedItem.weight >= 700 ? 400 : 700 })} />
                    <ToggleBtn icon={Italic} label="Italic" active={selectedItem.italic} onClick={() => updateItem(selectedId, { italic: !selectedItem.italic })} />
                    <ToggleBtn icon={Underline} label="Underline" active={selectedItem.underline} onClick={() => updateItem(selectedId, { underline: !selectedItem.underline })} />
                  </div>

                  <div className="mt-3">
                    <label className={labelClass} htmlFor={`${tabId}-font`}>Font Family</label>
                    <div className="flex gap-2">
                      <select id={`${tabId}-font`} name="font" value={selectedItem.font || settings?.default_font || 'RobotoCondensed.ttf'} onChange={handleChange} className={inputClass}>
                        <option value="arial.ttf">System Arial</option>
                        {fonts.map(f => (
                          <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                        ))}
                      </select>
                      <FileUploadButton label="Upload custom font" accept=".ttf,.otf" className="min-h-11 min-w-11 flex items-center justify-center bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 px-3 hover:bg-neutral-200 dark:hover:bg-neutral-700" onChange={event => { if (event.target.files[0]) uploadFont(event.target.files[0]); }}><Plus size={16} /></FileUploadButton>
                    </div>
                  </div>

                  <div className="flex gap-2 mt-3">
                    <ScrubberInput name="size" label="Font Size" value={selectedItem.size} onChange={handleChange} />
                    <ScrubberInput
                      name="lineHeight"
                      label="Line Height"
                      step={0.05}
                      dragMultiplier={0.01}
                      value={selectedItem.lineHeight ?? (String(selectedItem.text || '').includes('\n') ? 1.15 : 1)}
                      onChange={handleChange}
                    />
                    <ScrubberInput name="padding" label="Padding" value={selectedItem.padding !== undefined ? selectedItem.padding : 0} onChange={handleChange} />
                  </div>

                  <div className="flex gap-4 mt-2">
                    <div className="flex-1">
                      <label className={labelClass} htmlFor={`${tabId}-color`}>Text Color</label>
                      <select id={`${tabId}-color`} name="color" value={selectedItem.color || (selectedItem.invert ? 'white' : 'black')} onChange={handleChange} className={inputClass}>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className={labelClass} htmlFor={`${tabId}-background`}>Background</label>
                      <select id={`${tabId}-background`} name="bgColor" value={selectedItem.bgColor || (selectedItem.invert ? 'black' : (selectedItem.bg_white ? 'white' : 'transparent'))} onChange={handleChange} className={inputClass}>
                        <option value="transparent">Transparent</option>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                      </select>
                    </div>
                  </div>

                  <div className="flex gap-4 mt-2">
                    <MmScrubberInput name="width" label="Box Width" value={selectedItem.width || 0} onChange={handleChange} />
                  </div>

                  <div className="flex gap-4 mt-2">
                    <div className="flex-1">
                      <label className={labelClass} htmlFor={`${tabId}-horizontal`}>Horizontal</label>
                      <select id={`${tabId}-horizontal`} name="align" value={selectedItem.align || 'center'} onChange={handleChange} className={inputClass}>
                        <option value="left">Left</option>
                        <option value="center">Center</option>
                        <option value="right">Right</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className={labelClass} htmlFor={`${tabId}-vertical`}>Vertical</label>
                      <select id={`${tabId}-vertical`} name="verticalAlign" value={selectedItem.verticalAlign || 'middle'} onChange={handleChange} className={inputClass}>
                        <option value="top">Top</option>
                        <option value="middle">Middle</option>
                        <option value="bottom">Bottom</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="no_wrap" checked={selectedItem.no_wrap || false} onChange={handleChange} /> Single Line
                    </label>
                    <label className="flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-600 cursor-pointer">
                      <input type="checkbox" name="fit_to_width" checked={selectedItem.fit_to_width || false} onChange={handleChange} /> Auto-Fit to Box
                    </label>
                    {selectedItem.fit_to_width && (
                      <label className="col-span-2 flex items-center gap-2 text-[10px] uppercase font-bold text-neutral-500 cursor-pointer bg-neutral-50 dark:bg-neutral-900 p-2 border border-neutral-200 dark:border-neutral-800 mt-1">
                        <input type="checkbox" checked={selectedItem.batch_scale_mode === 'individual'} onChange={(e) => updateItem(selectedId, { batch_scale_mode: e.target.checked ? 'individual' : 'uniform' })} />
                        Scale Individually (Varies per record)
                      </label>
                    )}
                  </div>
                </>
              )}


              {selectedItem.type === 'group' && (
                <>
                  <div className="mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
                    <button onClick={() => useStore.getState().fitGroupToWidth()} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold">
                      Scale Group to Canvas Width
                    </button>
                  </div>
                </>
              )}

              {selectedItem.type === 'icon_text' && (
                <>
                  <div className="mb-4">
                    <button onClick={() => setShowIconPicker({ session: useStore.getState().documentSessionId, revision: useStore.getState().documentRevision, page: useStore.getState().currentPage })} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold">
                      Change Icon
                    </button>
                  </div>
                  <div className="flex gap-2 mb-2 bg-neutral-50 dark:bg-neutral-900 p-1 border border-neutral-200 dark:border-neutral-800">
                    <button onClick={() => updateItem(selectedId, { fit_to_width: true })} className="flex-1 text-[10px] uppercase font-bold text-blue-600 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors">
                      Auto-Fit to Box
                    </button>
                  </div>
                  <div>
                    <label className={labelClass} htmlFor={`${tabId}-group-text`}>Group Text</label>
                    <input id={`${tabId}-group-text`} type="text" name="text" value={selectedItem.text} onChange={handleChange} className={inputClass} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <ScrubberInput name="size" label="Text Size" value={Number(selectedItem.size || 0)} onChange={handleChange} />
                    <ScrubberInput name="weight" label="Weight (100-900)" value={selectedItem.weight || 700} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <MmScrubberInput name="icon_size" label="Icon Size" value={Number(selectedItem.icon_size || 0)} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2 pt-2 border-t border-neutral-100 dark:border-neutral-800">
                    <MmScrubberInput name="icon_x" label="Icon X" value={Math.round(selectedItem.icon_x)} onChange={handleChange} />
                    <MmScrubberInput name="icon_y" label="Icon Y" value={Math.round(selectedItem.icon_y)} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <MmScrubberInput name="text_x" label="Text X" value={Math.round(selectedItem.text_x)} onChange={handleChange} />
                    <MmScrubberInput name="text_y" label="Text Y" value={Math.round(selectedItem.text_y)} onChange={handleChange} />
                  </div>
                </>
              )}

              {selectedItem.type === 'html' && (
                <>
                  <div>
                    <label className={labelClass} htmlFor={`${tabId}-font`}>Font Family</label>
                    <div className="flex gap-2">
                      <select id={`${tabId}-font`} name="font" value={selectedItem.font || settings?.default_font || 'RobotoCondensed.ttf'} onChange={handleChange} className={inputClass}>
                        <option value="arial.ttf">System Arial</option>
                        {fonts.map(f => (
                          <option key={f.id} value={f.name}>{f.name.split('.')[0]}</option>
                        ))}
                      </select>
                      <FileUploadButton label="Upload custom font" accept=".ttf,.otf" className="min-h-11 min-w-11 flex items-center justify-center bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 px-3 hover:bg-neutral-200 dark:hover:bg-neutral-700" onChange={event => { if (event.target.files[0]) uploadFont(event.target.files[0]); }}><Plus size={16} /></FileUploadButton>
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className={labelClass.replace('mb-1.5', 'mb-0')} htmlFor={`${tabId}-html`}>HTML Content</label>
                      <button onClick={() => handleFormatHtml('item')} className="text-[9px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-sm font-bold uppercase hover:bg-blue-100 transition-colors">Format</button>
                    </div>
                    <textarea id={`${tabId}-html`} name="html" value={selectedItem.html || ''} onChange={handleChange} className={inputClass} rows={8} />
                  </div>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Frame Width" value={selectedItem.width} onChange={handleChange} />
                    <MmScrubberInput name="height" label="Frame Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                </>
              )}


              {selectedItem.type === 'image' && (
                <div className="flex gap-4">
                  <MmScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                  <MmScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                </div>
              )}

              {selectedItem.type === 'shape' && (
                <>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                    <MmScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                  <div className="flex gap-4 mt-2">
                    <div className="flex-1">
                      <label className={labelClass} htmlFor={`${tabId}-fill`}>Fill</label>
                      <select id={`${tabId}-fill`} name="fill" value={selectedItem.fill} onChange={handleChange} className={inputClass}>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                        <option value="transparent">Transparent</option>
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className={labelClass} htmlFor={`${tabId}-stroke`}>Stroke</label>
                      <select id={`${tabId}-stroke`} name="stroke" value={selectedItem.stroke} onChange={handleChange} className={inputClass}>
                        <option value="transparent">Transparent</option>
                        <option value="black">Black</option>
                        <option value="white">White</option>
                      </select>
                    </div>
                    <ScrubberInput name="strokeWidth" label="Thickness" value={selectedItem.strokeWidth || 0} onChange={handleChange} />
                  </div>
                </>
              )}

              {selectedItem.type === 'qrcode' && (
                <>
                  <div>
                    <label className={labelClass} htmlFor={`${tabId}-qr-data`}>QR Data (Supports {'{{ var }}'})</label>
                    <textarea id={`${tabId}-qr-data`} name="data" value={selectedItem.data} onChange={handleChange} className={inputClass} rows={3} />
                  </div>
                  <div className="flex gap-4">
                    {/* Scrubbing one axis updates both to maintain the square aspect ratio */}
                    <MmScrubberInput name="width" label="Size" value={selectedItem.width} onChange={(e) => {
                      handleChange({ target: { name: 'width', value: e.target.value, type: 'number' } });
                      handleChange({ target: { name: 'height', value: e.target.value, type: 'number' } });
                    }} />
                  </div>
                </>
              )}

              {selectedItem.type === 'barcode' && (
                <>
                  <div>
                    <label className={labelClass} htmlFor={`${tabId}-barcode-data`}>Barcode Data</label>
                    <input id={`${tabId}-barcode-data`} type="text" name="data" value={selectedItem.data} onChange={handleChange} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass} htmlFor={`${tabId}-barcode-type`}>Type</label>
                    <select id={`${tabId}-barcode-type`} name="barcode_type" value={selectedItem.barcode_type} onChange={handleChange} className={inputClass}>
                      <option value="code128">Code 128</option>
                      <option value="code39">Code 39</option>
                      <option value="ean13">EAN-13</option>
                    </select>
                  </div>
                  <div className="flex gap-4">
                    <MmScrubberInput name="width" label="Width" value={selectedItem.width} onChange={handleChange} />
                    <MmScrubberInput name="height" label="Height" value={selectedItem.height} onChange={handleChange} />
                  </div>
                </>
              )}

              {selectedItem && (
                <div className="mt-4 pt-4 border-t border-neutral-100 dark:border-neutral-800">
                  <label className={labelClass}>Duplicate Element Only</label>
                  <div className="flex gap-4 mb-2">
                    <div className="flex-1">
                      <label className="block text-[10px] text-neutral-600 dark:text-neutral-300 mb-1" htmlFor={`${tabId}-item-copies`}>Copies</label>
                      <input id={`${tabId}-item-copies`} type="number" min="1" value={dupCopies} onChange={e => setDupCopies(parseInt(e.target.value)||1)} className={inputClass} />
                    </div>
                    <div className="flex-1">
                      <label className="block text-[10px] text-neutral-600 dark:text-neutral-300 mb-1" htmlFor={`${tabId}-gap`}>Gap (mm)</label>
                      <input id={`${tabId}-gap`} type="number" min="0" value={dupGap} onChange={e => setDupGap(parseInt(e.target.value)||0)} className={inputClass} />
                    </div>
                  </div>
                  <button onClick={() => useStore.getState().duplicateItem(selectedId, dupCopies, dupGap)} className="w-full bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200 text-[10px] uppercase tracking-widest font-bold">
                    Clone Item Down
                  </button>
                </div>
              )}
              <div className="mt-2 mb-2 flex gap-4">
                  <div className="flex-1">
                    <label className={labelClass} htmlFor={`${tabId}-border-style`}>Styling Lines</label>
                    <select id={`${tabId}-border-style`} name="border_style" value={selectedItem.border_style || 'none'} onChange={handleChange} className={inputClass}>
                      <option value="none">None</option>
                      <option value="box">Box (Full)</option>
                      <option value="top">Top Border</option>
                      <option value="bottom">Bottom Border</option>
                      <option value="cut_line">Cut Line (Dashed)</option>
                    </select>
                  </div>
                  <ScrubberInput name="border_thickness" label="Thickness" value={selectedItem.border_thickness || 4} onChange={handleChange} />
              </div>
            </div>

            <div className="mt-auto pt-6">
              <button
                onClick={() => deleteItem(selectedId)}
                className="w-full bg-transparent text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900/50 px-4 py-2 rounded-none hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors text-xs uppercase tracking-widest font-medium"
              >
                Delete Item
              </button>
            </div>
    {showIconPicker && <LazyFeature label="icon picker" onClose={() => setShowIconPicker(false)}><IconPicker
      onClose={() => setShowIconPicker(false)} onSelect={source => {
        const current = useStore.getState();
        if (current.documentSessionId === showIconPicker.session && current.documentRevision === showIconPicker.revision
          && current.currentPage === showIconPicker.page && current.selectedId === selectedId) updateItem(selectedId, { icon_src: source });
        else useStore.setState({ apiError: 'The design changed while choosing an icon. Nothing was replaced.' });
        setShowIconPicker(false);
      }}
    /></LazyFeature>}
  </>;
}
