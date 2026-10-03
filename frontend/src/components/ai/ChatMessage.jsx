import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
const ChatMessage = ({ m }) => {
  if (m.role === 'tool') return null;
  if (m.role === 'assistant' && !m.content && m.tool_calls) return null;
  if (m.role === 'user' && Array.isArray(m.content)) return null;
  if (
    m.role === 'user' &&
    typeof m.content === 'string' &&
    (m.content.includes('[SYSTEM AUTO-INJECT]') || m.content.includes('[SYSTEM]'))
  ) {
    return null;
  }

  const isUser = m.role === 'user';

  return (
    <div className={`ai-chat-message flex flex-col ${isUser ? 'items-end' : 'items-start'} my-2`}>
      {m.content && typeof m.content === 'string' && (
        <div
          className={`p-3 rounded-lg max-w-[90%] text-sm shadow-xs ${
            isUser
              ? 'bg-blue-600 text-white'
              : 'bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100'
          }`}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap">{m.content}</div>
          ) : (
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {m.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  );
};


export default ChatMessage;
