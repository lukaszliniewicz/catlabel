import { expect, test, vi } from 'vitest';
import { CodeRenderCache } from './codeCache';

test('identical concurrent code requests share one generation and later copies reuse it', async () => {
  const cache = new CodeRenderCache(); let complete;
  const create = vi.fn(() => new Promise(resolve => { complete = resolve; }));
  const copies = Array.from({ length: 100 }, () => cache.getOrCreate('same', create));
  await Promise.resolve(); expect(create).toHaveBeenCalledTimes(1); complete('data:image/png;base64,sample');
  expect(await Promise.all(copies)).toEqual(Array(100).fill('data:image/png;base64,sample'));
  await cache.getOrCreate('same', create); expect(create).toHaveBeenCalledTimes(1);
});

test('entry and UTF-16 string budgets evict the least recently used result', async () => {
  const cache = new CodeRenderCache(2, 20), generate = vi.fn(async () => '1234');
  await cache.getOrCreate('a', generate); await cache.getOrCreate('b', generate); await cache.getOrCreate('a', generate);
  await cache.getOrCreate('c', generate); expect(cache.retainedBytes).toBe(20); expect(cache.entryCount).toBe(2);
  await cache.getOrCreate('a', generate); expect(generate).toHaveBeenCalledTimes(3);
  await cache.getOrCreate('b', generate); expect(generate).toHaveBeenCalledTimes(4);
});

test('oversized results render without retention, failures retry and keys stay distinct', async () => {
  const cache = new CodeRenderCache(2, 10), large = vi.fn(async () => 'larger than budget');
  await cache.getOrCreate('a', large); await cache.getOrCreate('a', large); expect(large).toHaveBeenCalledTimes(2); expect(cache.entryCount).toBe(0);
  await expect(cache.getOrCreate('bad', async () => { throw new Error('Failed'); })).rejects.toThrow('Failed');
  expect(await cache.getOrCreate('bad', async () => 'ok')).toBe('ok');
  const distinct = new CodeRenderCache(); expect(await distinct.getOrCreate('scale8', async () => 'a')).toBe('a');
  expect(await distinct.getOrCreate('scale12', async () => 'b')).toBe('b');
});

test('clearing prevents late pending results from reentering the cache', async () => {
  const cache = new CodeRenderCache(); let complete;
  const pending = cache.getOrCreate('a', () => new Promise(resolve => { complete = resolve; }));
  await Promise.resolve(); cache.clear(); complete('old'); expect(await pending).toBe('old'); expect(cache.entryCount).toBe(0);
  expect(await cache.getOrCreate('a', async () => 'new')).toBe('new');
});

test('pending storage stays bounded when unique requests exceed the budget', async () => {
  const cache = new CodeRenderCache(1, 1024); let complete;
  const pending = cache.getOrCreate('a', () => new Promise(resolve => { complete = resolve; }));
  await Promise.resolve(); expect(await cache.getOrCreate('b', async () => 'b')).toBe('b');
  expect(cache.pendingCount).toBe(1); expect(cache.entryCount).toBe(0); complete('a'); await pending;
  expect(cache.pendingCount).toBe(0); expect(cache.entryCount).toBe(1);
});
