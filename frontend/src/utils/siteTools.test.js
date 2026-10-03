import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiJson } from './apiClient';
import { registerSiteTools, siteToolContext } from './siteTools';

vi.mock('./apiClient', () => ({ apiJson: vi.fn() }));
const tool = {
  name: 'catlabel_design_create', description: 'Create a saved design.',
  inputSchema: { type: 'object', properties: { name: { type: 'string' } } },
  annotations: { readOnlyHint: false },
};
const context = () => ({ registerTool: vi.fn(), unregisterTool: vi.fn() });

beforeEach(() => vi.clearAllMocks());

describe('site tools share the MCP registry', () => {
  it('registers the supplied schema and returns image and structured results intact', async () => {
    const bridge = context();
    const onChange = vi.fn();
    const result = { content: [{ type: 'image', data: 'png-bytes', mimeType: 'image/png' }], structuredContent: { ok: true } };
    apiJson.mockResolvedValueOnce({ enabled: true, tools: [tool] }).mockResolvedValueOnce(result);
    const registration = await registerSiteTools(bridge, { onChange });
    const registered = bridge.registerTool.mock.calls[0][0];
    expect(registered.inputSchema).toBe(tool.inputSchema);
    expect(await registered.execute({ name: 'Parts' })).toBe(result);
    expect(apiJson.mock.calls[1][0]).toBe('/api/harness/tools/catlabel_design_create');
    expect(JSON.parse(apiJson.mock.calls[1][1].body)).toEqual({ arguments: { name: 'Parts' } });
    expect(onChange).toHaveBeenCalledWith(tool.name);
    expect(registration.count).toBe(1);
    registration.dispose();
    registration.dispose();
    expect(bridge.unregisterTool).toHaveBeenCalledExactlyOnceWith(tool.name);
  });

  it('does not register tools for a disabled installation', async () => {
    const bridge = context();
    apiJson.mockResolvedValue({ enabled: false, tools: [] });
    expect((await registerSiteTools(bridge)).enabled).toBe(false);
    expect(bridge.registerTool).not.toHaveBeenCalled();
  });

  it('cleans up partial registration on error', async () => {
    const bridge = context();
    bridge.registerTool.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('Registration rejected'));
    apiJson.mockResolvedValue({ enabled: true, tools: [tool, { ...tool, name: 'second' }] });
    await expect(registerSiteTools(bridge)).rejects.toThrow('Registration rejected');
    expect(bridge.unregisterTool).toHaveBeenCalledExactlyOnceWith(tool.name);
  });

  it('cleans up a registration that finishes after the page is closed', async () => {
    const bridge = context();
    const controller = new AbortController();
    bridge.registerTool.mockImplementation(() => controller.abort());
    apiJson.mockResolvedValue({ enabled: true, tools: [tool] });
    await expect(registerSiteTools(bridge, { signal: controller.signal })).rejects.toThrow();
    expect(bridge.unregisterTool).toHaveBeenCalledExactlyOnceWith(tool.name);
  });

  it('preserves tool errors without reporting a successful document change', async () => {
    const bridge = context();
    const onChange = vi.fn();
    const error = { isError: true, structuredContent: { ok: false, error: { code: 'revision_conflict' } } };
    apiJson.mockResolvedValueOnce({ enabled: true, tools: [tool] }).mockResolvedValueOnce(error);
    await registerSiteTools(bridge, { onChange });
    expect(await bridge.registerTool.mock.calls[0][0].execute({})).toBe(error);
    expect(onChange).not.toHaveBeenCalled();
  });
});

it('prefers the current document API and falls back to the older navigator API', () => {
  const current = context();
  const legacy = context();
  expect(siteToolContext(current, legacy)).toBe(current);
  expect(siteToolContext(undefined, legacy)).toBe(legacy);
  expect(siteToolContext({}, legacy)).toBe(legacy);
  expect(siteToolContext(undefined, undefined)).toBeUndefined();
});

it('uses an abort signal to remove registrations on the current document API', async () => {
  const current = { registerTool: vi.fn() };
  apiJson.mockResolvedValue({ enabled: true, tools: [tool] });
  const registration = await registerSiteTools(current);
  const signal = current.registerTool.mock.calls[0][1].signal;
  expect(signal.aborted).toBe(false);
  registration.dispose();
  expect(signal.aborted).toBe(true);
  expect(siteToolContext(current, undefined)).toBe(current);
});
