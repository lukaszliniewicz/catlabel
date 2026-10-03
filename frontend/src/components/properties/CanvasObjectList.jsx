import React, { useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useStore } from '../../store';
import { getPageItems } from '../../utils/canvasPages';

const labelFor = item => {
  const kind = { icon_text: 'Icon and text', qrcode: 'QR code', cut_line_indicator: 'Cut line' }[item.type]
    || `${item.type?.[0]?.toUpperCase() || ''}${item.type?.slice(1) || 'Object'}`;
  const description = item.type === 'group' ? `${item.children?.length || 0} grouped objects`
    : String(item.text || item.data || (item.type === 'html' ? 'Custom HTML' : '')).replace(/\s+/g, ' ').slice(0, 64);
  return description ? `${kind}: ${description}` : kind;
};

export default function CanvasObjectList() {
  const { items, currentPage, selectedIds, selectItem } = useStore(useShallow(state => ({
    items: state.items, currentPage: state.currentPage, selectedIds: state.selectedIds, selectItem: state.selectItem
  })));
  const objects = getPageItems(items, currentPage);
  const [focusedId, setFocusedId] = useState(null);
  const active = objects.some(item => item.id === focusedId) ? focusedId
    : objects.find(item => selectedIds.includes(item.id))?.id || objects[0]?.id;
  return <section className="mb-4 space-y-2 border-b border-neutral-200 pb-4 dark:border-neutral-800" aria-label="Objects on current label">
    <h2 className="font-serif text-lg">Label objects</h2>
    <p className="text-xs text-neutral-600 dark:text-neutral-300">Use arrow keys to browse, Enter to select, or Shift+Space to add or remove a selection. Groups select as one object.</p>
    {objects.length ? <div role="toolbar" aria-label="Select label objects" aria-orientation="vertical" className="max-h-44 overflow-y-auto space-y-1">
      {objects.map((item, index) => <button key={item.id} type="button" aria-pressed={selectedIds.includes(item.id)}
        tabIndex={active === item.id ? 0 : -1} onFocus={() => setFocusedId(item.id)}
        className={`min-h-11 w-full text-left px-3 py-2 border text-sm focus-visible:outline-2 focus-visible:outline-blue-600 ${selectedIds.includes(item.id) ? 'border-blue-600 bg-blue-50 text-blue-900 dark:bg-blue-950 dark:text-blue-100' : 'border-neutral-300 dark:border-neutral-700'}`}
        onClick={event => selectItem(item.id, event.shiftKey || event.ctrlKey || event.metaKey)}
        onKeyDown={event => {
          let next;
          if (event.key === 'ArrowDown') next = (index + 1) % objects.length;
          else if (event.key === 'ArrowUp') next = (index + objects.length - 1) % objects.length;
          else if (event.key === 'Home') next = 0;
          else if (event.key === 'End') next = objects.length - 1;
          else if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault(); selectItem(item.id, event.shiftKey || event.ctrlKey || event.metaKey); return;
          } else return;
          event.preventDefault(); event.currentTarget.parentElement.children[next].focus();
        }}>{labelFor(item)}</button>)}
    </div> : <p className="text-sm text-neutral-600 dark:text-neutral-300">No objects on this label. Add text, shapes or an image from the toolbar.</p>}
    {selectedIds.length > 0 && <button type="button" className="min-h-11 px-3 text-sm underline" onClick={() => selectItem(null)}>Clear object selection</button>}
  </section>;
}
