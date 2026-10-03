import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import CanvasPagePreview from './CanvasPagePreview';

vi.mock('react-konva', () => {
  const Primitive = ({ children }) => <div>{children}</div>;
  return {
    Group: Primitive, Layer: Primitive, Line: () => null, Path: () => null, Rect: () => null,
    Stage: ({ children, listening, draggable }) => <div data-stage data-listening={String(listening)} data-draggable={String(draggable)}>{children}</div>,
    Transformer: () => <div data-transformer />
  };
});
vi.mock('./CanvasItemNode', () => ({ default: ({ item, record, interactive, isSelected }) =>
  <div data-item={item.id} data-interactive={String(interactive)} data-selected={String(isSelected)}>{record.name}</div> }));
vi.mock('./HtmlLabel', () => ({ default: ({ html, record }) => <div data-html>{html} {record.name}</div> }));
vi.mock('./FloatingToolbar', () => ({ default: () => <div data-floating-toolbar /> }));

let root, container, observers, props;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  observers = [];
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback, options) { this.callback = callback; this.options = options; this.disconnect = vi.fn(); observers.push(this); }
    observe(element) { this.element = element; }
  });
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  props = {
    pageIndex: 2, pageNumber: 3, pageCount: 20, pageItems: [{ id: 'item', type: 'text' }],
    layout: { htmlContent: 'HTML content' }, record: { name: 'Primary record' }, isActive: true, showControls: true,
    isSelectedForPrint: true, rootRef: { current: container },
    view: { canvasWidth: 384, canvasHeight: 384, zoomScale: 1, canvasBorder: 'none', cvThick: 4, splitMode: false,
      isRotated: false, printPx: 384, selectedIds: ['item'], selectedItem: { id: 'item' }, stagePos: { x: 0, y: 0 } },
    interactions: { isPanning: false, trRef: { current: null }, snapLines: [], selectionBox: null,
      setSelectionBox: vi.fn(), setStagePos: vi.fn(), handleDragMove: vi.fn(), handleDragEnd: vi.fn(), handleItemPointerDown: vi.fn() },
    actions: { setCurrentPage: vi.fn(), togglePageForPrint: vi.fn(), printPages: vi.fn(), deletePage: vi.fn(), selectItem: vi.fn() }
  };
});
afterEach(async () => { await act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
const mount = () => act(() => root.render(<CanvasPagePreview {...props} />));
const intersect = visible => act(() => observers[0].callback([{ isIntersecting: visible }]));

test('the editing page stays mounted offscreen with one interactive stage and transformer', async () => {
  await mount(); await intersect(false);
  expect(container.querySelector('[data-stage]').dataset.listening).toBe('true');
  expect(container.querySelectorAll('[data-transformer]')).toHaveLength(1);
  expect(container.querySelector('[data-item]').dataset.selected).toBe('true');
  expect(container.querySelector('[data-floating-toolbar]')).not.toBeNull();
  expect(observers[0].options).toMatchObject({ root: container, rootMargin: '128px 0px' });
  await act(() => root.render(null)); expect(observers[0].disconnect).toHaveBeenCalledOnce();
});

test('a secondary batch record loads only near the viewport and never owns editing controls', async () => {
  props = { ...props, showControls: false, record: { name: 'Secondary record' } };
  await mount(); expect(container.querySelector('[data-stage]')).toBeNull();
  expect(container.querySelector('input')).toBeNull(); expect(container.querySelector('button')).toBeNull();
  await intersect(true);
  expect(container.querySelector('[data-stage]').dataset.listening).toBe('false');
  expect(container.querySelector('[data-item]').dataset.interactive).toBe('false');
  expect(container.querySelector('[data-item]').dataset.selected).toBe('false');
  expect(container.querySelector('[data-html]').textContent).toContain('Secondary record');
  expect(container.querySelector('[data-transformer]')).toBeNull();
  expect(container.querySelector('[data-floating-toolbar]')).toBeNull();
  await intersect(false); expect(container.querySelector('[data-stage]')).toBeNull(); expect(container.querySelector('[data-html]')).toBeNull();
});

test('an inactive primary page is read-only until selected and releases its stage again offscreen', async () => {
  props = { ...props, isActive: false };
  await mount(); expect(container.querySelector('[data-stage]')).toBeNull();
  await intersect(true); expect(container.querySelector('[data-stage]').dataset.listening).toBe('false');
  await act(() => container.querySelector('[aria-label="Edit label 3"]').click());
  expect(props.actions.setCurrentPage).toHaveBeenCalledWith(2);
  props = { ...props, isActive: true }; await mount(); await intersect(false);
  expect(container.querySelector('[data-stage]').dataset.listening).toBe('true');
  props = { ...props, isActive: false }; await mount(); expect(container.querySelector('[data-stage]')).toBeNull();
});

test('primary page actions retain the page index and panning suppresses item hit testing', async () => {
  props = { ...props, interactions: { ...props.interactions, isPanning: true } };
  await mount();
  expect(container.querySelector('[data-stage]').dataset.draggable).toBe('true');
  expect(container.querySelector('[data-item]').dataset.interactive).toBe('false');
  expect(container.querySelector('[data-transformer]')).toBeNull();
  await act(() => container.querySelector('[aria-label="Print label 3"]').click());
  await act(() => container.querySelector('[aria-label="Delete label 3"]').click());
  await act(() => container.querySelector('[aria-label="Select label 3 for printing"]').click());
  expect(props.actions.printPages).toHaveBeenCalledWith([2]);
  expect(props.actions.deletePage).toHaveBeenCalledWith(2);
  expect(props.actions.togglePageForPrint).toHaveBeenCalledWith(2);
});
