import { isObjectPayload } from '../utils/apiClient';

type JsonObject = Record<string, unknown>;
interface HistorySummary { id: number; title: string; updated_at?: string }
interface AiMessage extends JsonObject { role: string; content?: string | JsonObject[] | null }
interface ChatResult { error?: string; new_messages?: AiMessage[]; canvas_state?: JsonObject; usage?: JsonObject }
interface ToolResult { index: number; tool: string; status: 'success' | 'error' | 'confirmation_required'; result: string }
interface ManualResult { canvas_state: JsonObject; execution_results: ToolResult[] }
const positiveId = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const finiteNonnegative = (value: unknown): boolean => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const isMessage = (value: unknown): value is AiMessage => isObjectPayload(value)
  && typeof value.role === 'string' && ['system', 'developer', 'user', 'assistant', 'tool', 'function'].includes(value.role)
  && (value.content == null || typeof value.content === 'string' || (Array.isArray(value.content) && value.content.every(isObjectPayload)))
  && (value.tool_calls == null || (Array.isArray(value.tool_calls) && value.tool_calls.every(isObjectPayload)));
const isCanvasResult = (value: unknown): value is JsonObject => isObjectPayload(value)
  && (value.document_version == null || value.document_version === 1)
  && typeof value.width === 'number' && value.width > 0 && value.width <= 20_000
  && typeof value.height === 'number' && value.height > 0 && value.height <= 20_000
  && Array.isArray(value.items) && value.items.every(item => isObjectPayload(item) && typeof item.type === 'string' && typeof item.id === 'string')
  && (value.pageLayouts == null || (Array.isArray(value.pageLayouts) && value.pageLayouts.every(page => isObjectPayload(page) && typeof page.pageIndex === 'number' && typeof page.htmlContent === 'string')))
  && (value.__actions__ == null || (Array.isArray(value.__actions__) && value.__actions__.every(action => isObjectPayload(action) && typeof action.action === 'string')));

export const isHistoryList = (value: unknown): value is HistorySummary[] => Array.isArray(value)
  && value.every(row => isObjectPayload(row) && positiveId(row.id) && typeof row.title === 'string');
export const isHistoryDetail = (value: unknown): value is HistorySummary & { messages: AiMessage[] } => isObjectPayload(value)
  && positiveId(value.id) && typeof value.title === 'string' && Array.isArray(value.messages) && value.messages.every(isMessage);
export const isConversationCreated = (value: unknown): value is { id: number } => isObjectPayload(value) && positiveId(value.id);
export const isAiAcknowledgement = (value: unknown): value is { status: 'ok' } => isObjectPayload(value) && value.status === 'ok';
export const isExternalPrompt = (value: unknown): value is { prompt: string } => isObjectPayload(value) && typeof value.prompt === 'string' && value.prompt.trim().length > 0;
export const isChatResult = (value: unknown): value is ChatResult => isObjectPayload(value)
  && (typeof value.error === 'string' || (Array.isArray(value.new_messages) && value.new_messages.every(isMessage)))
  && (value.canvas_state == null || isCanvasResult(value.canvas_state))
  && (value.usage == null || (isObjectPayload(value.usage) && ['total_tokens', 'prompt_tokens', 'completion_tokens', 'cost'].every(key => value.usage && isObjectPayload(value.usage) && (value.usage[key] == null || finiteNonnegative(value.usage[key])))));
export const isManualResult = (value: unknown): value is ManualResult => isObjectPayload(value) && isCanvasResult(value.canvas_state)
  && Array.isArray(value.execution_results) && value.execution_results.every(row => isObjectPayload(row)
    && typeof row.index === 'number' && Number.isSafeInteger(row.index) && row.index >= 0 && typeof row.tool === 'string'
    && (row.status === 'success' || row.status === 'error' || row.status === 'confirmation_required') && typeof row.result === 'string');

export function extractToolCalls(rawText: string): JsonObject[] {
  let text = rawText.trim();
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  if (fenced?.[1]) text = fenced[1].trim();
  let parsed: unknown;
  try { parsed = JSON.parse(text); }
  catch {
    const first = text.indexOf('['), last = text.lastIndexOf(']');
    if (first < 0 || last <= first) throw new Error('Response is not a JSON array of tool calls.');
    parsed = JSON.parse(text.slice(first, last + 1));
  }
  const calls: unknown = Array.isArray(parsed) ? parsed : isObjectPayload(parsed) ? parsed.tool_calls : null;
  if (!Array.isArray(calls) || !calls.every(isObjectPayload)) throw new Error('Response is not a JSON array of tool calls.');
  return calls;
}
