import React, { useId } from 'react';
import { Loader2, Code, Check, Copy, Image as ImageIcon, ClipboardPaste, Sparkles } from 'lucide-react';

export default function ExternalAiPanel({ isEmpty, externalIntent, setExternalIntent, externalPrompt, externalResponse, setExternalResponse, externalError, externalNotice, externalResults, externalLoading, busy, promptCurrent, promptCopied, imageCopied, handleGenerateExternalPrompt, handleCopyExternalPrompt, handleCopyCanvasImage, handleExecuteExternal }) {
  const id = useId();
  return (
        <div className="flex-1 overflow-y-auto py-4 pr-2 flex flex-col gap-5">
          <div className="text-[10px] text-neutral-500 leading-relaxed bg-purple-50 dark:bg-purple-900/10 p-3 rounded-sm border border-purple-100 dark:border-purple-900/30">
            Use an external chat service with your own account.
            Generate the full tool-call prompt here, paste it into your external LLM, then paste the
            JSON tool-call response back below. You can also copy the current canvas as an image and
            paste it into the external chat for visual correction rounds.
          </div>

              {externalError && (
                <div role="alert" className="text-xs text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-3 border border-red-200 dark:border-red-900/50">
                  {externalError}
                </div>
              )}

              {externalNotice && !externalError && (
                <div role="status" className="text-xs text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20 p-3 border border-green-200 dark:border-green-900/50">
                  {externalNotice}
                </div>
              )}

          <div className="space-y-2">
            <label htmlFor={`${id}-intent`} className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest">
              1. Describe the change you want
            </label>
            <textarea
              id={`${id}-intent`}
              value={externalIntent}
              onChange={(e) => setExternalIntent(e.target.value)}
              placeholder={isEmpty ? "E.g. Design a shipping label for a fragile package." : "E.g. Move the product name up, make the barcode wider, and ensure nothing overlaps."}
              className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-3 text-sm dark:text-white focus:outline-hidden focus:border-purple-500 transition-colors min-h-[96px]"
            />
            <button
              onClick={handleGenerateExternalPrompt}
              disabled={busy || !externalIntent.trim()}
              className="min-h-11 w-full bg-purple-700 text-white p-2 hover:bg-purple-700 transition-colors disabled:opacity-50 text-xs uppercase tracking-widest font-bold flex items-center justify-center gap-2"
            >
              {externalLoading ? <Loader2 size={14} className="animate-spin" /> : <Code size={14} />}
              Generate Prompt
            </button>
          </div>

          {externalPrompt && (
            <div className="space-y-2">
              <label htmlFor={`${id}-prompt`} className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest">
                2. Copy this prompt into ChatGPT or Claude
              </label>
              <textarea
                id={`${id}-prompt`}
                value={externalPrompt}
                readOnly
                className="w-full bg-neutral-50 dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-700 p-3 text-[10px] font-mono text-neutral-600 dark:text-neutral-300 min-h-[180px]"
              />
              <div className="flex gap-2">
                <button
                  disabled={busy}
                  onClick={handleCopyExternalPrompt}
                  className="min-h-11 flex-1 bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white p-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors text-xs flex items-center justify-center gap-2 border border-neutral-200 dark:border-neutral-800"
                >
                  {promptCopied ? (
                    <Check size={14} className="text-green-500" />
                  ) : (
                    <Copy size={14} />
                  )}
                  {promptCopied ? 'Prompt Copied' : 'Copy Prompt'}
                </button>
                <button
                  disabled={busy}
                  onClick={handleCopyCanvasImage}
                  className="min-h-11 flex-1 bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white p-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors text-xs flex items-center justify-center gap-2 border border-neutral-200 dark:border-neutral-800"
                >
                  {imageCopied ? (
                    <Check size={14} className="text-green-500" />
                  ) : (
                    <ImageIcon size={14} />
                  )}
                  {imageCopied ? 'Image Copied' : 'Copy Image'}
                </button>
              </div>
            </div>
          )}

          {externalPrompt && (
            <div className="space-y-2">
              {!promptCurrent && <p role="status" className="text-xs text-neutral-800 dark:text-neutral-200">The design or conversation changed. Generate a fresh prompt before applying a response.</p>}
              <label htmlFor={`${id}-response`} className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest flex items-center gap-2">
                <ClipboardPaste size={12} />
                3. Paste the external AI response
              </label>
              <textarea
                id={`${id}-response`}
                value={externalResponse}
                onChange={(e) => setExternalResponse(e.target.value)}
                placeholder='Paste the JSON array here, e.g. [{"tool":"add_text_element","arguments":{...}}]'
                className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 p-3 text-sm font-mono dark:text-white focus:outline-hidden focus:border-purple-500 transition-colors min-h-[180px]"
              />


              <button
                onClick={handleExecuteExternal}
                disabled={busy || !promptCurrent || !externalResponse.trim()}
                className="min-h-11 w-full bg-purple-700 text-white p-2 hover:bg-purple-700 transition-colors disabled:opacity-50 text-xs uppercase tracking-widest font-bold flex items-center justify-center gap-2"
              >
                {externalLoading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Sparkles size={14} />
                )}
                Apply Tool Calls
              </button>
            </div>
          )}

          {externalResults.length > 0 && (
            <div className="space-y-2">
              <div className="text-[10px] font-bold text-neutral-600 dark:text-neutral-300 uppercase tracking-widest">
                Execution Results
              </div>
              <div className="border border-neutral-200 dark:border-neutral-800 divide-y divide-neutral-200 dark:divide-neutral-800">
                {externalResults.map((result) => (
                  <div
                    key={`${result.index}-${result.tool}`}
                    className="p-3 flex flex-col gap-1 bg-white dark:bg-neutral-950"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-bold dark:text-white">{result.tool}</span>
                      <span
                        className={`text-[10px] uppercase tracking-widest font-bold ${
                          result.status === 'success'
                            ? 'text-green-600 dark:text-green-400'
                            : result.status === 'error' ? 'text-red-600 dark:text-red-400' : 'text-neutral-700 dark:text-neutral-300'
                        }`}
                      >
                        {result.status === 'confirmation_required' ? 'Needs confirmation' : result.status}
                      </span>
                    </div>
                    <div className="text-[11px] text-neutral-500 dark:text-neutral-400 wrap-break-word">
                      {result.result}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
  );
}
