import { apiJson } from './apiClient';

export function siteToolContext(documentContext, navigatorContext) {
  return [documentContext, navigatorContext].find(context => (
    typeof context?.registerTool === 'function'
  ));
}

// Tool names, schemas and execution come from the existing MCP registry.
export async function registerSiteTools(context, { signal, onChange = () => {} } = {}) {
  const response = await apiJson('/api/harness/tools', { signal });
  if (!response.enabled) return { enabled: false, count: 0, dispose: () => {} };
  const registered = [];
  const registrationController = new AbortController();
  const dispose = () => {
    registrationController.abort();
    if (typeof context.unregisterTool === 'function') {
      for (const name of registered.splice(0)) context.unregisterTool(name);
    } else registered.length = 0;
  };
  try {
    for (const tool of response.tools) {
      signal?.throwIfAborted();
      await context.registerTool({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema,
        annotations: {
          readOnlyHint: tool.annotations?.readOnlyHint === true,
          consequentialHint: tool.annotations?.destructiveHint === true,
        },
        execute: async (argumentsValue, options = {}) => {
          const requestSignal = options.signal && signal
            ? AbortSignal.any([options.signal, signal])
            : options.signal || signal;
          const result = await apiJson(`/api/harness/tools/${encodeURIComponent(tool.name)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ arguments: argumentsValue }),
            signal: requestSignal,
          }, { timeoutMs: 90_000 });
          if (!result.isError) onChange(tool.name);
          return result;
        },
      }, { signal: registrationController.signal });
      registered.push(tool.name);
      signal?.throwIfAborted();
    }
    return { enabled: true, count: registered.length, dispose };
  } catch (error) {
    dispose();
    throw error;
  }
}
