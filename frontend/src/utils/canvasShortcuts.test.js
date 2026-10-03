import { afterEach, expect, test } from 'vitest';
import { ignoreCanvasShortcut } from './canvasShortcuts';

afterEach(() => document.body.replaceChildren());
test.each(['input', 'textarea', 'select', 'div[contenteditable=true]', 'div[role=textbox]', 'div[role=treeitem]', 'button[role=tab]'])('shortcuts leave %s interaction alone', selector => {
  const [tag, attribute] = selector.split('[');
  const element = document.createElement(tag);
  if (attribute) { const [key, value] = attribute.slice(0, -1).split('='); element.setAttribute(key, value); }
  document.body.append(element);
  expect(ignoreCanvasShortcut({ target: element, key: 'Delete', code: 'Delete' })).toBe(true);
});
test('a covering modal scopes canvas shortcuts even when focus is outside it', () => {
  document.body.innerHTML = '<div aria-modal="true" role="dialog"></div><button>Elsewhere</button>';
  expect(ignoreCanvasShortcut({ target: document.querySelector('button'), key: 'z', code: 'KeyZ' })).toBe(true);
});
test('Space activates toolbar buttons while undo remains available outside editable areas', () => {
  const button = document.createElement('button'); document.body.append(button);
  expect(ignoreCanvasShortcut({ target: button, key: ' ', code: 'Space' })).toBe(true);
  expect(ignoreCanvasShortcut({ target: button, key: 'z', code: 'KeyZ' })).toBe(false);
});
