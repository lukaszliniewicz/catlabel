import { expect, test } from 'vitest';
import { buildElementChange, centerElement, fitElementWidth, resolveElementDimension } from './elementEditing';
const image = extra => ({ id: 'image', type: 'image', width: '50%', height: '25%', ...extra });

test('percentage dimensions center and resize images without producing NaN', () => {
  expect(centerElement(image(), 400, 200)).toEqual({ x: 100, y: 75 });
  expect(fitElementWidth(image(), 400, 200)).toEqual({ x: 0, width: 400, height: 100, align: 'center' });
  expect(buildElementChange(image(), { name: 'width', value: 100, type: 'number' }, 400, 200)).toEqual({ width: 100, height: 25 });
  expect(buildElementChange(image(), { name: 'height', value: 100, type: 'number' }, 400, 200)).toEqual({ height: 100, width: 400 });
});

test.each(['', Infinity, NaN, true, 'invalid', '-1', '0'])('invalid width %s cannot corrupt image geometry', value => {
  expect(buildElementChange(image(), { name: 'width', value, type: 'number' }, 400, 200)).toBeNull();
});

test('an image without a valid ratio updates one dimension safely', () => {
  expect(buildElementChange(image({ width: 0, height: 0 }), { name: 'width', value: 100, type: 'number' }, 400, 200)).toEqual({ width: 100 });
});

test('automatic text height accounts for lines, padding and legacy missing size', () => {
  expect(centerElement({ id: 'text', type: 'text', text: 'one\ntwo', size: 10, width: 100, invert: true }, 400, 200)).toEqual({ x: 150, y: 84.5 });
  expect(centerElement({ id: 'text', type: 'text', text: 'one', width: 100 }, 400, 200)).toEqual({ x: 150, y: 94 });
});

test('ordinary text, checkbox and signed position changes retain their value types', () => {
  expect(buildElementChange(image(), { name: 'text', value: '12', type: 'text' }, 400, 200)).toEqual({ text: '12' });
  expect(buildElementChange(image(), { name: 'invert', value: 'on', checked: true, type: 'checkbox' }, 400, 200)).toEqual({ invert: true });
  expect(buildElementChange(image(), { name: 'x', value: '-12', type: 'number' }, 400, 200)).toEqual({ x: -12 });
  expect(resolveElementDimension('broken%', 400)).toBe(0); expect(resolveElementDimension('25%', 400)).toBe(100);
});


test('QR size changes update both axes in one valid patch', () => {
  const qr = { id: 'qr', type: 'qrcode', width: 20, height: 20 };
  expect(buildElementChange(qr, { name: 'width', value: 80, type: 'number' }, 400, 200)).toEqual({ width: 80, height: 80 });
  expect(buildElementChange(qr, { name: 'width', value: 0, type: 'number' }, 400, 200)).toBeNull();
});
