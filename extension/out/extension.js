"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const path = __importStar(require("path"));
const vscode = __importStar(require("vscode"));
const serverManager_1 = require("./serverManager");
const dependencyInstaller_1 = require("./dependencyInstaller");
const smellsProvider_1 = require("./smellsProvider");
let outputChannel;
async function activate(context) {
    outputChannel = vscode.window.createOutputChannel('ReactRefactor');
    outputChannel.appendLine('[ReactRefactor] Activating...');
    // Register smells sidebar
    const smellsProvider = new smellsProvider_1.SmellsProvider();
    const treeView = vscode.window.createTreeView('reactRefactorSmells', {
        treeDataProvider: smellsProvider,
        showCollapseAll: true,
    });
    context.subscriptions.push(treeView);
    // Status bar — selected count
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    statusBar.text = '$(check) 0 smells selected';
    statusBar.tooltip = 'ReactRefactor: selected smells for fixing';
    statusBar.show();
    context.subscriptions.push(statusBar);
    // --- E2-S4 helpers: time + cost estimates ---
    function formatTime(seconds) {
        if (seconds < 60) {
            return `~${seconds}s`;
        }
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return s > 0 ? `~${m}m ${s}s` : `~${m}m`;
    }
    function getEstimates(count) {
        const seconds = Math.ceil(count * 25 / 3);
        const cost = (count * 0.005).toFixed(3);
        return { timeStr: formatTime(seconds), costStr: `$${cost}` };
    }
    // Keep status bar, view description, and context key in sync with checkbox changes
    smellsProvider.onDidChangeSelection(count => {
        if (count === 0) {
            statusBar.text = '$(check) 0 smells selected';
            treeView.description = undefined;
        }
        else {
            const { timeStr, costStr } = getEstimates(count);
            statusBar.text = `$(check) ${count} selected · ${timeStr} · ${costStr}`;
            treeView.description = `${count} selected · ${timeStr} · ${costStr}`;
        }
        vscode.commands.executeCommand('setContext', 'reactRefactor.hasSelection', count > 0);
    });
    // Forward tree view checkbox events to the provider
    treeView.onDidChangeCheckboxState(e => {
        for (const [node, state] of e.items) {
            smellsProvider.handleCheckboxChange(node, state);
        }
    });
    // --- E4-S1: run summary Webview panel ---
    function showReportPanel(workspace, summary, results) {
        const panel = vscode.window.createWebviewPanel('reactRefactorReport', 'ReactRefactor — Fix Report', vscode.ViewColumn.One, { enableScripts: true });
        const hasErrors = results.some(r => r.error);
        const rows = results.map(({ smell, status, error }) => {
            const colors = {
                accepted: '#4caf50', rejected: '#f44336', skipped: '#ff9800',
                failed: '#e91e63', queued: '#9e9e9e', running: '#2196f3',
            };
            const color = colors[status] ?? '#9e9e9e';
            const file = smell.file_path.split(/[\\/]/).pop() ?? smell.file_path;
            const component = smell.component_name ?? '—';
            const errorCell = hasErrors
                ? `<td class="error-cell">${error ?? ''}</td>`
                : '';
            return `<tr>
                <td>${component}</td>
                <td title="${smell.file_path}">${file}</td>
                <td>${smell.smell_type}</td>
                <td><span class="badge" style="background:${color}">${status}</span></td>
                ${errorCell}
            </tr>`;
        }).join('');
        const acceptedCount = results.filter(r => r.status === 'accepted').length;
        panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 16px; }
  h2 { margin-top: 0; }
  .summary { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
  .stat { background: var(--vscode-editor-inactiveSelectionBackground); border-radius: 6px; padding: 8px 16px; }
  .stat span { font-size: 1.6em; font-weight: bold; display: block; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; border-bottom: 1px solid var(--vscode-panel-border); padding: 6px 8px; }
  td { padding: 6px 8px; border-bottom: 1px solid var(--vscode-panel-border); }
  .badge { border-radius: 4px; padding: 2px 8px; color: #fff; font-size: 0.85em; }
  button { margin-top: 20px; padding: 8px 18px; background: var(--vscode-button-background);
           color: var(--vscode-button-foreground); border: none; border-radius: 4px; cursor: pointer; font-size: 1em; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button:disabled { opacity: 0.4; cursor: default; }
  .error-cell { color: var(--vscode-errorForeground); font-size: 0.85em; max-width: 300px; }
</style>
</head>
<body>
<h2>Fix Report</h2>
<div class="summary">
  <div class="stat"><span>${summary.accepted ?? 0}</span>Accepted</div>
  <div class="stat"><span>${summary.rejected ?? 0}</span>Rejected</div>
  <div class="stat"><span>${summary.skipped ?? 0}</span>Skipped</div>
  <div class="stat"><span>${summary.failed ?? 0}</span>Failed</div>
</div>
<table>
  <thead><tr><th>Component</th><th>File</th><th>Smell Type</th><th>Status</th>${hasErrors ? '<th>Error</th>' : ''}</tr></thead>
  <tbody>${rows}</tbody>
</table>
${acceptedCount > 0 ? `<button id="revertAll">Revert All Accepted (${acceptedCount})</button>` : ''}
<script>
  const vscode = acquireVsCodeApi();
  const btn = document.getElementById('revertAll');
  if (btn) {
    btn.addEventListener('click', () => {
      btn.disabled = true;
      btn.textContent = 'Reverting…';
      vscode.postMessage({ command: 'revertAll' });
    });
  }
  window.addEventListener('message', e => {
    if (e.data.command === 'revertDone') {
      if (btn) { btn.textContent = e.data.success ? 'Reverted' : 'Revert failed'; }
    }
  });
</script>
</body>
</html>`;
        // Handle "Revert All" from Webview
        panel.webview.onDidReceiveMessage(async (msg) => {
            if (msg.command !== 'revertAll') {
                return;
            }
            const accepted = results.filter(r => r.status === 'accepted');
            let failed = 0;
            for (const { smell } of accepted) {
                try {
                    const res = await fetch(`http://localhost:${smellsProvider_1.SERVER_PORT}/revert`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ workspace, file: smell.file_path }),
                    });
                    if (!res.ok) {
                        failed++;
                    }
                }
                catch {
                    failed++;
                }
            }
            panel.webview.postMessage({ command: 'revertDone', success: failed === 0 });
            if (failed === 0) {
                vscode.window.showInformationMessage(`ReactRefactor: reverted ${accepted.length} file(s).`);
            }
            else {
                vscode.window.showWarningMessage(`ReactRefactor: ${failed} revert(s) failed. Check Output Channel.`);
            }
        });
    }
    // --- E3-S3 / E3-S4: stream live fix progress via SSE, with cancel support ---
    let _currentJobId = null;
    async function runFix(workspace, selected) {
        outputChannel.appendLine(`[ReactRefactor] Fixing ${selected.length} smell(s)…`);
        for (const s of selected) {
            smellsProvider.setFixStatus(s.smell_id, 'queued');
        }
        statusBar.text = `$(sync~spin) Fixing ${selected.length} smell(s)…`;
        vscode.commands.executeCommand('setContext', 'reactRefactor.fixRunning', true);
        try {
            const fixRes = await fetch(`http://localhost:${smellsProvider_1.SERVER_PORT}/fix`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace, smells: selected }),
            });
            if (!fixRes.ok) {
                throw new Error(`Server returned ${fixRes.status}: ${await fixRes.text()}`);
            }
            const { job_id } = await fixRes.json();
            _currentJobId = job_id;
            outputChannel.appendLine(`[ReactRefactor] Job started: ${job_id}`);
            const progRes = await fetch(`http://localhost:${smellsProvider_1.SERVER_PORT}/progress/${job_id}`);
            if (!progRes.ok || !progRes.body) {
                throw new Error(`Progress stream failed: ${progRes.status}`);
            }
            const reader = progRes.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            outer: while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    break;
                }
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() ?? '';
                for (const line of lines) {
                    if (!line.startsWith('data: ')) {
                        continue;
                    }
                    const raw = line.slice(6).trim();
                    if (!raw || raw === '{"type": "ping"}') {
                        continue;
                    }
                    let event;
                    try {
                        event = JSON.parse(raw);
                    }
                    catch {
                        continue;
                    }
                    if (event.type === 'node_done') {
                        smellsProvider.setFixStatus(event.smell_id, 'running');
                        outputChannel.appendLine(`  node: ${event.node}  (${event.smell_id})`);
                    }
                    else if (event.type === 'task_done') {
                        const taskError = event.error != null ? String(event.error) : undefined;
                        const retryCount = typeof event.retry_count === 'number' ? event.retry_count : undefined;
                        const critiqueScore = event.critique_score != null ? Number(event.critique_score) : undefined;
                        const rejectionReason = event.rejection_reason != null ? String(event.rejection_reason) : undefined;
                        smellsProvider.setFixStatus(event.smell_id, event.status, taskError, retryCount, critiqueScore, rejectionReason);
                        outputChannel.appendLine(`  task done: ${event.smell_id} → ${event.status} (retries=${event.retry_count ?? 0}${critiqueScore !== undefined ? `, score=${critiqueScore.toFixed(2)}` : ''}${taskError ? `, error: ${taskError}` : ''})`);
                        if (rejectionReason) {
                            outputChannel.appendLine(`  rejection reason:\n${rejectionReason.split('\n').map(l => `    ${l}`).join('\n')}`);
                        }
                    }
                    else if (event.type === 'run_complete') {
                        const s = event.summary;
                        outputChannel.appendLine(`[ReactRefactor] Run complete — accepted:${s.accepted} rejected:${s.rejected} skipped:${s.skipped} failed:${s.failed}`);
                        showReportPanel(workspace, s, smellsProvider.getFixResults());
                        vscode.window.showInformationMessage(`ReactRefactor: ${s.accepted} fixed, ${s.rejected} rejected, ${s.skipped} skipped, ${s.failed} failed`);
                        break outer;
                    }
                    else if (event.type === 'cancelled') {
                        const s = event.summary;
                        outputChannel.appendLine(`[ReactRefactor] Job cancelled — completed:${event.completed} cancelled:${s.cancelled}`);
                        vscode.window.showWarningMessage(`ReactRefactor: job cancelled (${event.completed} task(s) completed before cancel)`);
                        break outer;
                    }
                }
            }
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            outputChannel.appendLine(`[ReactRefactor] Fix error: ${msg}`);
            vscode.window.showErrorMessage(`ReactRefactor fix failed: ${msg}`);
            smellsProvider.clearFixStatus();
        }
        finally {
            _currentJobId = null;
            vscode.commands.executeCommand('setContext', 'reactRefactor.fixRunning', false);
            const count = smellsProvider.getSelectedCount();
            if (count === 0) {
                statusBar.text = '$(check) 0 smells selected';
            }
            else {
                const { timeStr, costStr } = getEstimates(count);
                statusBar.text = `$(check) ${count} selected · ${timeStr} · ${costStr}`;
            }
        }
    }
    // Fix Selected command — confirmation dialog with time + cost summary
    const fixSelectedCommand = vscode.commands.registerCommand('reactRefactor.fixSelected', async () => {
        const selected = smellsProvider.getSelectedSmells();
        if (selected.length === 0) {
            return;
        }
        const folders = vscode.workspace.workspaceFolders;
        if (!folders || folders.length === 0) {
            vscode.window.showWarningMessage('ReactRefactor: No workspace folder is open.');
            return;
        }
        const { timeStr, costStr } = getEstimates(selected.length);
        const answer = await vscode.window.showInformationMessage(`Fix ${selected.length} smell${selected.length !== 1 ? 's' : ''}?`, {
            modal: true,
            detail: `Estimated time: ${timeStr}\nEstimated cost: ${costStr}`,
        }, 'Fix Now');
        if (answer !== 'Fix Now') {
            return;
        }
        await runFix(folders[0].uri.fsPath, selected);
    });
    context.subscriptions.push(fixSelectedCommand);
    // Cancel a running fix job
    const cancelFixCommand = vscode.commands.registerCommand('reactRefactor.cancelFix', async () => {
        if (!_currentJobId) {
            return;
        }
        try {
            const res = await fetch(`http://localhost:${smellsProvider_1.SERVER_PORT}/jobs/${_currentJobId}`, { method: 'DELETE' });
            if (res.status === 409) {
                vscode.window.showInformationMessage('ReactRefactor: job already finished.');
            }
            else if (!res.ok) {
                throw new Error(`Server returned ${res.status}`);
            }
            else {
                outputChannel.appendLine(`[ReactRefactor] Cancel requested for job ${_currentJobId}`);
            }
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            vscode.window.showErrorMessage(`ReactRefactor: cancel failed — ${msg}`);
        }
    });
    context.subscriptions.push(cancelFixCommand);
    // Open a file and highlight the smell's line range
    const openSmellCommand = vscode.commands.registerCommand('reactRefactor.openSmell', async (filePath, lineStart, lineEnd) => {
        const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        const editor = await vscode.window.showTextDocument(doc, { preserveFocus: false });
        const range = new vscode.Range(new vscode.Position(Math.max(0, lineStart - 1), 0), new vscode.Position(Math.max(0, lineEnd - 1), Number.MAX_SAFE_INTEGER));
        editor.selection = new vscode.Selection(range.start, range.end);
        editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
    });
    context.subscriptions.push(openSmellCommand);
    // --- E4-S2: inline diff view ---
    // Virtual document provider — serves git-original content fetched from /original
    const _originalCache = new Map();
    const originalProvider = vscode.workspace.registerTextDocumentContentProvider('reactrefactor-original', { provideTextDocumentContent(uri) { return _originalCache.get(uri.toString()) ?? ''; } });
    context.subscriptions.push(originalProvider);
    const viewDiffCommand = vscode.commands.registerCommand('reactRefactor.viewDiff', async (smell, status) => {
        const folders = vscode.workspace.workspaceFolders;
        const workspace = folders?.[0]?.uri.fsPath ?? '';
        // For non-accepted smells just show what happened
        if (status !== 'accepted') {
            const label = {
                rejected: 'The pipeline rejected this fix — no changes were made.',
                skipped: 'This smell was skipped by the pipeline.',
                failed: 'The pipeline failed to process this smell.',
            };
            vscode.window.showInformationMessage(`ReactRefactor (${status}): ${label[status] ?? 'No diff available.'}`);
            return;
        }
        // Derive relative path for git (server expects forward-slash relative path)
        const relFile = path.relative(workspace, smell.file_path).replace(/\\/g, '/');
        try {
            const res = await fetch(`http://localhost:${smellsProvider_1.SERVER_PORT}/original?` +
                `file=${encodeURIComponent(relFile)}&workspace=${encodeURIComponent(workspace)}`);
            if (res.status === 404) {
                vscode.window.showInformationMessage(`ReactRefactor: "${relFile}" is not tracked by git — cannot show original.`);
                return;
            }
            if (!res.ok) {
                throw new Error(`Server returned ${res.status}`);
            }
            const data = await res.json();
            // Cache content under a stable URI and open diff
            const originalUri = vscode.Uri.parse(`reactrefactor-original:/${encodeURIComponent(relFile)}`);
            _originalCache.set(originalUri.toString(), data.content);
            const currentUri = vscode.Uri.file(smell.file_path);
            const title = `${smell.component_name ?? smell.smell_type}: original ↔ current`;
            await vscode.commands.executeCommand('vscode.diff', originalUri, currentUri, title);
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            vscode.window.showErrorMessage(`ReactRefactor: diff failed — ${msg}`);
        }
    });
    context.subscriptions.push(viewDiffCommand);
    // --- E4-S4: inline revert action on accepted smells ---
    const revertSmellCommand = vscode.commands.registerCommand('reactRefactor.revertSmell', async (smell) => {
        const folders = vscode.workspace.workspaceFolders;
        const workspace = folders?.[0]?.uri.fsPath ?? '';
        const relFile = path.relative(workspace, smell.file_path).replace(/\\/g, '/');
        try {
            const res = await fetch(`http://localhost:${smellsProvider_1.SERVER_PORT}/revert`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace, file: relFile }),
            });
            if (!res.ok) {
                const text = await res.text();
                throw new Error(`Server returned ${res.status}: ${text}`);
            }
            smellsProvider.setFixStatus(smell.smell_id, 'reverted');
            vscode.window.showInformationMessage(`ReactRefactor: reverted ${smell.component_name ?? smell.smell_type} in ${path.basename(smell.file_path)}.`);
        }
        catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            vscode.window.showErrorMessage(`ReactRefactor: revert failed — ${msg}`);
        }
    });
    context.subscriptions.push(revertSmellCommand);
    // Select top 100 smells by severity
    const selectTop100Command = vscode.commands.registerCommand('reactRefactor.selectTop100', () => {
        const total = smellsProvider.getSmells().length;
        if (total === 0) {
            vscode.window.showWarningMessage('ReactRefactor: No smells loaded. Run a scan first.');
            return;
        }
        smellsProvider.selectTopN(100);
        const selected = smellsProvider.getSelectedCount();
        vscode.window.showInformationMessage(`ReactRefactor: Selected top ${selected} smell${selected !== 1 ? 's' : ''} by severity.`);
    });
    context.subscriptions.push(selectTop100Command);
    // Register the scan command
    const scanCommand = vscode.commands.registerCommand('reactRefactor.scanProject', async () => {
        const folders = vscode.workspace.workspaceFolders;
        if (!folders || folders.length === 0) {
            vscode.window.showWarningMessage('ReactRefactor: No workspace folder is open.');
            return;
        }
        await (0, smellsProvider_1.runScan)(folders[0].uri.fsPath, smellsProvider, outputChannel);
    });
    context.subscriptions.push(scanCommand);
    // Step 1 — find Python (now returns PythonInfo with path + version)
    const pythonInfo = await (0, serverManager_1.detectPython)(outputChannel, context);
    if (!pythonInfo) {
        vscode.window.showErrorMessage('ReactRefactor requires Python 3.8+. Could not find a Python installation.', 'Select Python Interpreter').then(selection => {
            if (selection === 'Select Python Interpreter') {
                vscode.commands.executeCommand('python.selectInterpreter');
            }
        });
        outputChannel.appendLine('[ReactRefactor] ERROR: Python not found. Extension inactive.');
        return;
    }
    if (pythonInfo.version.endsWith(':TOO_OLD')) {
        const found = pythonInfo.version.replace(':TOO_OLD', '');
        vscode.window.showErrorMessage(`ReactRefactor requires Python 3.8 or higher. Found: ${found}`, 'Select Python Interpreter').then(selection => {
            if (selection === 'Select Python Interpreter') {
                vscode.commands.executeCommand('python.selectInterpreter');
            }
        });
        outputChannel.appendLine(`[ReactRefactor] ERROR: Python ${found} is too old. Extension inactive.`);
        return;
    }
    // Step 2 — ensure Python dependencies are installed
    const depsReady = await (0, dependencyInstaller_1.ensureDependencies)(pythonInfo.path, outputChannel, context);
    if (!depsReady) {
        return;
    }
    // Step 3 — start the server
    const started = await (0, serverManager_1.startServer)(pythonInfo.path, outputChannel, context.extensionPath);
    if (!started) {
        vscode.window.showErrorMessage('ReactRefactor: Server failed to start. Check the ReactRefactor Output Channel for details.');
        return;
    }
    vscode.window.showInformationMessage('ReactRefactor is ready.');
    outputChannel.show(true);
}
function deactivate() {
    if (outputChannel) {
        (0, serverManager_1.stopServer)(outputChannel);
        outputChannel.appendLine('[ReactRefactor] Deactivated.');
    }
}
//# sourceMappingURL=extension.js.map