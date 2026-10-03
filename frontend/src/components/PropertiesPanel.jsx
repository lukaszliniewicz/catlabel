import { MmScrubberInput, ScrubberInput } from './NumericInput';
import LazyFeature from './LazyFeature';
import EditorDrawer from './EditorDrawer';
import React, { useState, useEffect, useId, useRef } from 'react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import {
  AlignCenter, MoveHorizontal, Maximize2, Sliders, Printer, Database, Sparkles,
  Plus, Bold, Italic, Underline
} from 'lucide-react';
import { calculateAutoFitItem } from '../utils/rendering';
import TemplateSettings from './properties/TemplateSettings';
import CanvasSettings from './properties/CanvasSettings';
import PrinterSettings from './properties/PrinterSettings';
import GlobalDefaults from './properties/GlobalDefaults';
import FileUploadButton from './FileUploadButton';
import { inputClass, labelClass } from './properties/styles';
import BatchDataPanel from './BatchDataPanel';

const AIAssistant = React.lazy(() => import('./AIAssistant'));
const IconPicker = React.lazy(() => import('./IconPicker'));

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

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, deleteItem, canvasWidth, canvasHeight, settings, fonts, uploadFont, selectedPrinterInfo, splitMode, setSplitMode, batchRecords, pageLayouts, currentPage, setHtmlContent, updateTemplateParams, ejectTemplate, isPropertiesOpen, toggleProperties } = useStore(useShallow(state => ({
    items: state.items,
    selectedId: state.selectedId,
    updateItem: state.updateItem,
    deleteItem: state.deleteItem,
    canvasWidth: state.canvasWidth,
    canvasHeight: state.canvasHeight,
    settings: state.settings,
    fonts: state.fonts,
    uploadFont: state.uploadFont,
    selectedPrinterInfo: state.selectedPrinterInfo,
    splitMode: state.splitMode,
    setSplitMode: state.setSplitMode,
    batchRecords: state.batchRecords,
    pageLayouts: state.pageLayouts,
    currentPage: state.currentPage,
    setHtmlContent: state.setHtmlContent,
    updateTemplateParams: state.updateTemplateParams,
    ejectTemplate: state.ejectTemplate,
    isPropertiesOpen: state.isPropertiesOpen,
    toggleProperties: state.toggleProperties,
  })));
  const selectedItem = items.find(i => i.id === selectedId);
  const isNarrowLayout = useStore(state => state.isNarrowLayout);
  const isPreCut = selectedPrinterInfo?.media_type === 'pre-cut';

  const [panelWidth, setPanelWidth] = useState(360);
  const resize = useRef(null);

  // Tab State
  const [activeTab, setActiveTab] = useState('canvas');
  const tabId = useId();
  const [showIconPicker, setShowIconPicker] = useState(false);
  const [templateIconField, setTemplateIconField] = useState(null);
  
  const currentLayout = pageLayouts.find(l => l.pageIndex === currentPage) || { htmlContent: '', activeTemplate: null };
  const activeTemplate = currentLayout.activeTemplate;
  const htmlContent = currentLayout.htmlContent;

  const [previousSelection, setPreviousSelection] = useState(selectedId);
  if (previousSelection !== selectedId) {
    setPreviousSelection(selectedId);
    if (selectedItem) setActiveTab('element');
  }

  // Refresh untouched defaults while retaining unsaved or failed draft edits.
  const [settingsDraft, setSettingsDraft] = useState({ source: settings, value: settings });
  const localSettings = settingsDraft.source === settings ? settingsDraft.value
    : settingsDraft.value === settingsDraft.source ? settings : settingsDraft.value;
  if (settingsDraft.source !== settings) setSettingsDraft({ source: settings, value: localSettings });
  const setLocalSettings = (value) => setSettingsDraft({ source: settings, value });

  const [dupCopies, setDupCopies] = useState(1);
  const [dupGap, setDupGap] = useState(10);
  const [multCopies, setMultCopies] = useState(1);
  

  useEffect(() => {
    if (isPreCut && splitMode) {
      setSplitMode(false);
    }
  }, [isPreCut, splitMode, setSplitMode]);

  const endResize = event => {
    if (resize.current?.pointerId !== event.pointerId) return;
    resize.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };


  // --- Actions ---

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

  const handleFormatHtml = async target => {
    const stamp = useStore.getState();
    const source = target === 'designMode' ? htmlContent : selectedItem?.html || '';
    try {
      const beautify = (await import('js-beautify')).default;
      const current = useStore.getState();
      if (current.documentSessionId !== stamp.documentSessionId || current.documentRevision !== stamp.documentRevision
        || current.currentPage !== stamp.currentPage || (target === 'item' && current.selectedId !== selectedId)) {
        useStore.setState({ apiError: 'The design changed while formatting was loading. Your latest edits were kept.' });
        return;
      }
      const formatted = beautify.html(source, { indent_size: 2 });
      if (target === 'designMode') setHtmlContent(formatted);
      else if (selectedItem?.type === 'html') updateItem(selectedId, { html: formatted });
    } catch (error) { useStore.setState({ apiError: error.message || 'HTML formatting could not be loaded. Your content was kept.' }); }
  };


  if (!isPropertiesOpen) return null;

  const content = (
    <div
      className="relative h-full bg-white dark:bg-neutral-950 border-l border-neutral-200 dark:border-neutral-800 flex flex-col z-10 overflow-hidden transition-colors duration-300 shrink-0"
      style={{ width: panelWidth, maxWidth: '100%' }}
    >
      {!isNarrowLayout && <div
        role="separator"
        aria-label="Resize properties panel"
        aria-orientation="vertical"
        aria-valuemin={280}
        aria-valuemax={600}
        aria-valuenow={panelWidth}
        tabIndex={0}
        className="absolute left-0 top-0 bottom-0 w-3 cursor-col-resize hover:bg-blue-500 z-50 transition-colors focus-visible:outline-2 focus-visible:outline-blue-600"
        style={{ touchAction: 'none' }}
        onPointerDown={event => {
          if (event.pointerType === 'mouse' && event.button !== 0) return;
          event.preventDefault();
          resize.current = { pointerId: event.pointerId, x: event.clientX, width: panelWidth };
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={event => {
          const start = resize.current;
          if (start?.pointerId === event.pointerId) setPanelWidth(Math.max(280, Math.min(600, start.width + start.x - event.clientX)));
        }}
        onPointerUp={endResize} onPointerCancel={endResize} onLostPointerCapture={() => { resize.current = null; }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') { event.preventDefault(); setPanelWidth((width) => Math.min(600, width + 10)); }
          if (event.key === 'ArrowRight') { event.preventDefault(); setPanelWidth((width) => Math.max(280, width - 10)); }
        }}
      />}

      
      <div className="flex shrink-0 border-b border-neutral-200 dark:border-neutral-800" role="tablist" aria-label="Properties sections">
        {[
          { id: 'element', label: 'Element and layout', Icon: Sliders },
          { id: 'canvas', label: 'Canvas and printer', Icon: Printer },
          { id: 'data', label: 'Batch data', Icon: Database },
          { id: 'assistant', label: 'AI assistant', Icon: Sparkles }
        ].map(({ id, label, Icon }, index, tabs) => (
          <button key={id} id={`${tabId}-tab-${id}`} type="button" role="tab"
            aria-selected={activeTab === id} aria-label={label} aria-controls={`${tabId}-panel-${id}`}
            tabIndex={activeTab === id ? 0 : -1} onClick={() => setActiveTab(id)}
            onKeyDown={event => {
              let next;
              if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
              else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
              else if (event.key === 'Home') next = 0;
              else if (event.key === 'End') next = tabs.length - 1;
              else return;
              event.preventDefault();
              setActiveTab(tabs[next].id);
              document.getElementById(`${tabId}-tab-${tabs[next].id}`)?.focus();
            }}
            className={`flex min-h-12 flex-1 justify-center items-center border-b-2 transition-colors focus-visible:outline-2 focus-visible:outline-blue-600 ${activeTab === id ? 'border-blue-600 text-blue-700 bg-blue-50 dark:bg-blue-900/20 dark:text-blue-300' : 'border-transparent text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-900'}`}>
            <Icon size={20} />
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${tabId}-panel-${activeTab}`} aria-labelledby={`${tabId}-tab-${activeTab}`} className="p-6 overflow-y-auto flex-1 flex flex-col gap-6">

        {/* === CANVAS & PRINTER TAB === */}
        {activeTab === 'canvas' && <>
          <CanvasSettings multCopies={multCopies} setMultCopies={setMultCopies} />
          <PrinterSettings />
          <GlobalDefaults localSettings={localSettings} setLocalSettings={setLocalSettings} />
        </>}

        {/* === ELEMENT TAB === */}
        {activeTab === 'element' && (
          <>
            {!selectedItem ? (
              <TemplateSettings layout={currentLayout} onEject={ejectTemplate} onChangeParams={updateTemplateParams}
                onPickIcon={setTemplateIconField} onFormat={() => handleFormatHtml('designMode')} onChangeHtml={setHtmlContent} />
            ) : selectedItem && (
              <>
            <div className="space-y-4">
              <div>
                <div className="grid grid-cols-3 gap-2">
                  <MmScrubberInput name="x" label="X Pos" value={selectedItem.x} onChange={handleChange} />
                  <MmScrubberInput name="y" label="Y Pos" value={selectedItem.y} onChange={handleChange} />
                  <ScrubberInput name="rotation" label="Rot(°)" value={Math.round(selectedItem.rotation || 0)} onChange={handleChange} />
                </div>
                
                <div className="flex gap-2 mt-3">
                  <button onClick={handleCenterAbsolute} title="Center Absolutely" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                    <AlignCenter size={16} />
                  </button>
                  <button onClick={handleMakeFullWidth} title="Full Width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
                    <MoveHorizontal size={16} />
                  </button>
                  {selectedItem.type === 'text' && (
                    <button onClick={handleFitToWidth} title="Maximize Font to Width" className="flex-1 flex justify-center items-center bg-neutral-100 dark:bg-neutral-900 text-neutral-600 dark:text-neutral-400 py-2 hover:bg-blue-50 hover:text-blue-600 transition-colors border border-transparent hover:border-blue-200">
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
                  <div className="flex gap-4">
                    <MmScrubberInput name="x" label="X Pos" value={selectedItem.x} onChange={handleChange} />
                    <MmScrubberInput name="y" label="Y Pos" value={selectedItem.y} onChange={handleChange} />
                  </div>
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
                    <button onClick={() => setShowIconPicker(true)} className="w-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 py-2 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors border border-blue-200 dark:border-blue-800 text-[10px] uppercase tracking-widest font-bold">
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
              </>
            )}
          </>
        )}

        {/* === DATA TAB === */}
        {activeTab === 'data' && <BatchDataPanel />}

        {/* === ASSISTANT TAB === */}
        {activeTab === 'assistant' && (
          <LazyFeature label="AI assistant" inline onClose={() => setActiveTab('canvas')}>
            <AIAssistant />
          </LazyFeature>
        )}
      </div>

        {showIconPicker && (
          <LazyFeature label="icon picker" onClose={() => setShowIconPicker(false)}><IconPicker
            onClose={() => setShowIconPicker(false)}
            onSelect={(b64) => {
              updateItem(selectedId, { icon_src: b64 });
              setShowIconPicker(false);
            }}
          /></LazyFeature>
        )}
        {templateIconField && activeTemplate && (
          <LazyFeature label="template icon picker" onClose={() => setTemplateIconField(null)}><IconPicker
            onClose={() => setTemplateIconField(null)}
            onSelect={(b64) => {
              updateTemplateParams({ [templateIconField]: b64 });
              setTemplateIconField(null);
            }}
          /></LazyFeature>
        )}
    </div>
  );
  return isNarrowLayout ? <EditorDrawer label="Properties" width={panelWidth} onClose={toggleProperties}>{content}</EditorDrawer> : content;
}
