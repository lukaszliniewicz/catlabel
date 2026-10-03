import LazyFeature from './LazyFeature';
import EditorDrawer from './EditorDrawer';
import React, { useState, useEffect, useId, useRef } from 'react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import {
  Sliders, Printer, Database, Sparkles
} from 'lucide-react';
import TemplateSettings from './properties/TemplateSettings';
import ElementSettings from './properties/ElementSettings';
import CanvasObjectList from './properties/CanvasObjectList';
import CanvasSettings from './properties/CanvasSettings';
import PrinterSettings from './properties/PrinterSettings';
import GlobalDefaults from './properties/GlobalDefaults';
import BatchDataPanel from './BatchDataPanel';

const AIAssistant = React.lazy(() => import('./AIAssistant'));
const IconPicker = React.lazy(() => import('./IconPicker'));

export default function PropertiesPanel() {
  const { items, selectedId, updateItem, settings, selectedPrinterInfo, splitMode, setSplitMode, pageLayouts, currentPage, setHtmlContent, updateTemplateParams, ejectTemplate, isPropertiesOpen, toggleProperties } = useStore(useShallow(state => ({
    items: state.items,
    selectedId: state.selectedId,
    updateItem: state.updateItem,
    settings: state.settings,
    selectedPrinterInfo: state.selectedPrinterInfo,
    splitMode: state.splitMode,
    setSplitMode: state.setSplitMode,
    pageLayouts: state.pageLayouts,
    currentPage: state.currentPage,
    setHtmlContent: state.setHtmlContent,
    updateTemplateParams: state.updateTemplateParams,
    ejectTemplate: state.ejectTemplate,
    isPropertiesOpen: state.isPropertiesOpen,
    toggleProperties: state.toggleProperties,
  })));
  const selectedItem = items.find(i => i.id === selectedId);
  const documentSessionId = useStore(state => state.documentSessionId);
  const documentRevision = useStore(state => state.documentRevision);
  const isNarrowLayout = useStore(state => state.isNarrowLayout);
  const isPreCut = selectedPrinterInfo?.media_type === 'pre-cut';

  const [panelWidth, setPanelWidth] = useState(360);
  const resize = useRef(null);

  // Tab State
  const [activeTab, setActiveTab] = useState('canvas');
  const tabId = useId();
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
            <CanvasObjectList />
            {!selectedItem ? (
              <TemplateSettings layout={currentLayout} onEject={ejectTemplate} onChangeParams={updateTemplateParams}
                onPickIcon={field => setTemplateIconField({ field, session: documentSessionId, revision: documentRevision, page: currentPage, template: activeTemplate.id })} onFormat={() => handleFormatHtml('designMode')} onChangeHtml={setHtmlContent} />
            ) : selectedItem && (
              <>
              <ElementSettings key={`${documentSessionId}-${selectedItem.id}`} selectedItem={selectedItem} dupCopies={dupCopies} setDupCopies={setDupCopies}
                dupGap={dupGap} setDupGap={setDupGap} handleFormatHtml={handleFormatHtml} />
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

        {templateIconField && activeTemplate && templateIconField.session === documentSessionId
          && templateIconField.revision === documentRevision && templateIconField.page === currentPage && (
          <LazyFeature label="template icon picker" onClose={() => setTemplateIconField(null)}><IconPicker
            onClose={() => setTemplateIconField(null)}
            onSelect={(b64) => {
              const current = useStore.getState();
              if (current.documentSessionId === templateIconField.session && current.documentRevision === templateIconField.revision
                && current.currentPage === templateIconField.page && current.pageLayouts.find(layout => layout.pageIndex === current.currentPage)?.activeTemplate?.id === templateIconField.template) {
                updateTemplateParams({ [templateIconField.field]: b64 });
              } else useStore.setState({ apiError: 'The design changed while choosing an icon. Nothing was replaced.' });
              setTemplateIconField(null);
            }}
          /></LazyFeature>
        )}
    </div>
  );
  return isNarrowLayout ? <EditorDrawer label="Properties" width={panelWidth} onClose={toggleProperties}>{content}</EditorDrawer> : content;
}
