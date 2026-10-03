const sanitize = value => {
  if (typeof value === 'string' && value.startsWith('data:image/') && value.length > 100) return '[Image omitted from trace copy]';
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, sanitize(entry)]));
  return value;
};

export function buildAiTranscript(messages, usage, traces = null) {
  let out = '# CatLabel AI Session Debug Report\n\n';
  out += `**Session Tokens:** ${(usage.tokens || 0).toLocaleString()}\n`;
  out += `**Prompt Tokens:** ${(usage.promptTokens || 0).toLocaleString()}\n`;
  out += `**Completion Tokens:** ${(usage.completionTokens || 0).toLocaleString()}\n`;
  out += `**Estimated Cost:** $${Number(usage.cost || 0).toFixed(4)}\n\n---\n\n`;
  if (traces) out += `## RAW LLM TRACES (Database Logs)\n\n\`\`\`json\n${JSON.stringify(sanitize(traces), null, 2)}\n\`\`\`\n\n---\n\n`;
  out += '## UI MESSAGE HISTORY\n\n';
  for (const message of messages) {
    out += `### [${message.role.toUpperCase()}]\n\n`;
    if (message.role !== 'tool' && message.content) {
      if (typeof message.content === 'string') out += `${message.content}\n\n`;
      else if (Array.isArray(message.content)) out += `${message.content.find(part => part.type === 'text')?.text || ''}\n\n*[Image Attached]*\n\n`;
    }
    for (const call of message.tool_calls || []) {
      out += `**Tool Call:** \`${call.function?.name || 'unknown'}\`\n\n\`\`\`json\n`;
      try { out += `${JSON.stringify(sanitize(JSON.parse(call.function?.arguments || '{}')), null, 2)}\n`; }
      catch { out += `${String(call.function?.arguments || '').slice(0, 500)}\n`; }
      out += '```\n\n';
    }
    if (message.role === 'tool') out += `> **Tool Result:**\n> ${String(message.content || '').replace(/\n/g, '\n> ')}\n\n`;
  }
  return out;
}
