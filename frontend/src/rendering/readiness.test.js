import { expect, test, vi } from 'vitest';
import { createRenderReadiness, loadRenderImage } from './readiness';

test('capture waits for every resource, including newly mounted code images', async () => {
  const job = createRenderReadiness();
  const code = Symbol();
  const image = Symbol();
  job.set(code, false);
  const complete = vi.fn();
  const wait = job.wait().then(complete);
  await Promise.resolve();
  expect(complete).not.toHaveBeenCalled();
  job.set(image, false);
  job.set(code, true);
  await Promise.resolve();
  expect(complete).not.toHaveBeenCalled();
  job.set(image, true);
  await wait;
  expect(complete).toHaveBeenCalledOnce();
});

test('failed and cancelled resources reject capture instead of returning blank output', async () => {
  const job = createRenderReadiness();
  const token = Symbol();
  job.set(token, false);
  const failure = expect(job.wait()).rejects.toThrow('broken image');
  job.set(token, true, new Error('broken image'));
  await failure;
  job.remove(token);
  job.set(token, false);
  const controller = new AbortController();
  const cancellation = expect(job.wait(controller.signal)).rejects.toThrow('cancelled');
  controller.abort();
  await cancellation;
});

test('image failure and deadline reject, and cancelled loads cannot complete later', async () => {
  vi.useFakeTimers();
  const images = [];
  vi.stubGlobal('Image', class { constructor() { images.push(this); } });
  try {
    const failed = expect(loadRenderImage('broken')).rejects.toThrow('could not be loaded');
    images[0].onerror();
    await failed;
    const timed = expect(loadRenderImage('slow')).rejects.toThrow('8 seconds');
    await vi.advanceTimersByTimeAsync(8_000);
    await timed;
    const controller = new AbortController();
    const cancelled = expect(loadRenderImage('late', controller.signal)).rejects.toThrow('cancelled');
    controller.abort();
    await cancelled;
    expect(images[2].onload).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});
