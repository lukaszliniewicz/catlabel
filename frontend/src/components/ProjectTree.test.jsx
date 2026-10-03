import React, { act } from 'react';
import { Blob as TestBlob } from 'node:buffer';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import ProjectTree from './ProjectTree';
import { useStore } from '../store';
import * as apiClient from '../utils/apiClient';
let root, container;
const original = useStore.getState();
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(() => root.unmount()); container.remove(); useStore.setState(original, true); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
test('tree owns named nested rows and supports roving navigation without activating nested actions', async () => {
  const loadProject = vi.fn();
  useStore.setState({ projects: [{ id: 1, name: 'Child', category_id: 1 }, { id: 2, name: 'Root' }], categories: [{ id: 1, name: 'Folder' }], loadProject });
  await act(() => root.render(<ProjectTree />));
  const rows = () => [...container.querySelectorAll('[role=treeitem]')];
  const key = async (element, value) => act(() => element.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })));
  expect(container.querySelector('[role=tree]').getAttribute('aria-label')).toBe('Saved projects and folders');
  expect(rows().map(row => row.tabIndex)).toEqual([0, -1]);
  await key(rows()[0], 'ArrowRight');
  expect(document.getElementById(rows()[0].getAttribute('aria-owns')).getAttribute('role')).toBe('group');
  await key(rows()[0], 'ArrowRight');
  expect(document.activeElement).toBe(rows()[1]);
  expect(rows().filter(row => row.tabIndex === 0)).toEqual([rows()[1]]);
  await key(rows()[1], 'ArrowLeft'); expect(document.activeElement).toBe(rows()[0]);
  await key(rows()[0], 'End'); expect(document.activeElement).toBe(rows()[2]);
  await key(rows()[2].querySelector('button'), 'Enter'); expect(loadProject).not.toHaveBeenCalled();
  await key(rows()[2], 'Enter'); expect(loadProject).toHaveBeenCalledOnce();
  await act(() => useStore.setState({ projects: [{ id: 1, name: 'Child', category_id: 1 }] }));
  expect(rows()[0].tabIndex).toBe(0);
});

const mountProject = async overrides => {
  useStore.setState({ projects: [{ id: 42, name: 'Saved', revision: 3 }], categories: [], ...overrides });
  await act(() => root.render(<ProjectTree />));
  await act(() => container.querySelector('[aria-label="Actions for Saved"]').click());
};
const choose = text => act(() => [...document.querySelectorAll('[role=dialog] button')].find(button => button.textContent.includes(text)).click());
test('individual export fetches detail omitted from summaries and releases its blob URL', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('Blob', TestBlob);
  const canvas = { document_version: 1, dpi: 300, width: 600, items: [{ id: 'actual' }] };
  const api = vi.spyOn(apiClient, 'apiJson').mockResolvedValue({ id: 42, name: 'Saved', canvas_state: canvas });
  let blob;
  const url = class extends URL { static createObjectURL(value) { blob = value; return 'blob:fixture'; } static revokeObjectURL = vi.fn(); };
  vi.stubGlobal('URL', url);
  const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await mountProject(); await choose('Export JSON');
  expect(api).toHaveBeenCalledWith('/api/projects/42', {}, expect.any(Object));
  const raw = await blob.text();
  expect(JSON.parse(raw)).toEqual({ catlabel_export_version: '1.0', data: { type: 'project', name: 'Saved', canvas_state: canvas } });
  expect(anchorClick).toHaveBeenCalledOnce();
  await act(() => vi.advanceTimersByTime(1)); expect(url.revokeObjectURL).toHaveBeenCalledWith('blob:fixture');
});
test('missing saved document leaves an export error and does not download an empty project', async () => {
  vi.spyOn(apiClient, 'apiJson').mockResolvedValue({ id: 42, name: 'Saved' });
  const download = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await mountProject(); await choose('Export JSON');
  expect(container.querySelector('[role=alert]').textContent).toContain('missing or malformed');
  expect(download).not.toHaveBeenCalled();
});
test('overwrite has an explicit cancel and rejects intervening edits before any update', async () => {
  const update = vi.fn();
  await mountProject({ updateProject: update }); await choose('Overwrite with Current');
  await choose('Cancel'); expect(update).not.toHaveBeenCalled();
  await act(() => container.querySelector('[aria-label="Actions for Saved"]').click()); await choose('Overwrite with Current');
  await act(() => useStore.getState().setItems([{ id: 'new-edit', type: 'text' }]));
  await choose('Overwrite saved project');
  expect(update).not.toHaveBeenCalled();
  expect(document.querySelector('[role=dialog] [role=alert]').textContent).toContain('changed');
});
test('approved overwrite uses the frozen saved revision and retains contextual failure', async () => {
  const update = vi.fn(async () => { useStore.setState({ apiError: 'Saved revision conflict' }); return false; });
  await mountProject({ updateProject: update }); await choose('Overwrite with Current'); await choose('Overwrite saved project');
  expect(update).toHaveBeenCalledWith(42, null, undefined, 3);
  expect(document.querySelector('[role=dialog] [role=alert]').textContent).toBe('Saved revision conflict');
  expect([...document.querySelectorAll('[role=dialog] button')].every(button => !button.disabled)).toBe(true);
});
test('delete is only called after the explicit destructive choice', async () => {
  const remove = vi.fn().mockResolvedValue(true);
  await mountProject({ deleteProject: remove }); await choose('Delete'); await choose('Cancel'); expect(remove).not.toHaveBeenCalled();
  await act(() => container.querySelector('[aria-label="Actions for Saved"]').click()); await choose('Delete'); await choose('Delete saved project');
  expect(remove).toHaveBeenCalledWith(42); expect(document.querySelector('[role=dialog]')).toBeNull();
});
