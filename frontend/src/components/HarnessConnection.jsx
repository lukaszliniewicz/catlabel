import React, { useEffect, useState } from 'react';
import EditorDrawer from './EditorDrawer';
import { apiJson } from '../utils/apiClient';
import { opencodeLaunchCommand } from '../utils/harnessConnection';

export default function HarnessConnection({ onClose, siteTools }) {
  const [connection, setConnection] = useState(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    apiJson('/api/harness/connection', { signal: controller.signal })
      .then(setConnection)
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message || 'Connection details could not be loaded.'); });
    return () => controller.abort();
  }, []);
  const copyAddress = async () => {
    try {
      await navigator.clipboard.writeText(window.location.origin);
      setCopied('address');
    } catch {
      setError('Copy the app address from your browser’s address bar.');
    }
  };
  const copyOpenCodeCommand = async () => {
    try {
      await navigator.clipboard.writeText(opencodeLaunchCommand(connection.opencode_config_path));
      setCopied('opencode');
    } catch {
      setError('Copy the command below and paste it into your terminal.');
    }
  };
  return <EditorDrawer label="Connect AI harness" width={440} onClose={onClose}>
    <div className="h-full overflow-y-auto space-y-6 p-5 text-sm leading-relaxed">
      {error && <p role="alert" className="text-red-700 dark:text-red-300">{error}</p>}
      {!connection && !error && <p role="status">Checking connection…</p>}
      {connection?.enabled === false && <section className="space-y-2">
        <h3 className="font-semibold">Enable harness support</h3>
        <p>Close CatLabel, then launch it with <code>--install-mcp</code>. New desktop installations include this support by default.</p>
        <p>For a source installation, run <code>bash ./run.sh --install-mcp</code> or <code>run.bat --install-mcp</code> on Windows.</p>
      </section>}
      {connection?.enabled && <>
        <section className="space-y-3">
          <h3 className="font-semibold text-base">ChatGPT Work / Codex desktop</h3>
          <p>Open this app address in your harness’s built-in browser, then ask it to design a label. Compatible browsers discover CatLabel’s tools automatically.</p>
          <div className="rounded-sm border border-neutral-300 dark:border-neutral-700 p-3 break-all font-mono text-xs">{window.location.origin}</div>
          <button type="button" onClick={copyAddress} className="min-h-10 border border-neutral-400 rounded-sm px-3">{copied === 'address' ? 'Address copied' : 'Copy app address'}</button>
          <p role="status" className="text-xs text-neutral-600 dark:text-neutral-400">{siteTools.state === 'ready'
            ? `${siteTools.count} site tools available in this browser.`
            : siteTools.state === 'failed'
              ? 'Site-tool registration failed. Reopen the app in a compatible built-in browser or use MCP below.'
              : 'Site tools require a compatible browser and enabled browser/workspace permissions. A normal browser can still use the editor.'}</p>
        </section>
        <section className="space-y-3">
          <h3 className="font-semibold text-base">OpenCode</h3>
          <p>CatLabel prepares a private connection file automatically. Copy the launch command, paste it into your terminal and start a private OpenCode session:</p>
          {connection.opencode_config_path && <><pre className="whitespace-pre-wrap break-all border border-neutral-300 dark:border-neutral-700 p-3 text-xs">{opencodeLaunchCommand(connection.opencode_config_path)}</pre>
            <button type="button" onClick={copyOpenCodeCommand} className="min-h-10 border border-neutral-400 rounded-sm px-3">{copied === 'opencode' ? 'Command copied' : 'Copy OpenCode command'}</button></>}
          {connection.configuration_error && <p className="text-amber-700 dark:text-amber-300">The configuration file could not be prepared. Use the launcher’s <code>--mcp-config --mcp-output /absolute/path/opencode.json</code> command with a new output path.</p>}
          <p className="text-xs text-neutral-600 dark:text-neutral-400">Check /mcps and wait for CatLabel to connect before asking for a design. For an existing shared service, merge the file’s CatLabel entry into its MCP settings, run opencode reload and reconnect. Keep the generated file and token on this computer.</p>
        </section>
        <section className="space-y-2">
          <h3 className="font-semibold">Other MCP clients</h3>
          <p className="break-all font-mono text-xs">{connection.url}</p>
          <p>Use Streamable HTTP with CatLabel’s private bearer credential. The MCP guide covers manual setup and connection checks.</p>
        </section>
        <section className="space-y-2 border-t border-neutral-300 dark:border-neutral-700 pt-4">
          <h3 className="font-semibold">A shared workflow</h3>
          <p>Tools work with saved projects. Save your current canvas first, or ask the harness to create a new named design. Review its preview and printer choice before starting a physical print.</p>
          <p className="text-xs text-neutral-600 dark:text-neutral-400">Keep CatLabel running. A cloud-only chat cannot reach a printer on this computer through its localhost address.</p>
        </section>
      </>}
    </div>
  </EditorDrawer>;
}
