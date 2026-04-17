import * as vscode from 'vscode';
import { detectPython, startServer, stopServer } from './serverManager';
import { ensureDependencies } from './dependencyInstaller';
import { SmellsProvider, runScan, SERVER_PORT, FixStatus } from './smellsProvider';

let outputChannel: vscode.OutputChannel;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    outputChannel = vscode.window.createOutputChannel('ReactRefactor');
    outputChannel.appendLine('[ReactRefactor] Activating...');

    // Register smells sidebar
    const smellsProvider = new SmellsProvider();
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
    function formatTime(seconds: number): string {
        if (seconds < 60) { return `~${seconds}s`; }
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return s > 0 ? `~${m}m ${s}s` : `~${m}m`;
    }

    function getEstimates(count: number): { timeStr: string; costStr: string } {
        const seconds = Math.ceil(count * 25 / 3);
        const cost = (count * 0.005).toFixed(3);
        return { timeStr: formatTime(seconds), costStr: `$${cost}` };
    }

    // Keep status bar, view description, and context key in sync with checkbox changes
    smellsProvider.onDidChangeSelection(count => {
        if (count === 0) {
            statusBar.text = '$(check) 0 smells selected';
            treeView.description = undefined;
        } else {
            const { timeStr, costStr } = getEstimates(count);
            statusBar.text = `$(check) ${count} selected · ${timeStr} · ${costStr}`;
            treeView.description = `${count} selected · ${timeStr} · ${costStr}`;
        }
        vscode.commands.executeCommand('setContext', 'reactRefactor.hasSelection', count > 0);
    });

    // Forward tree view checkbox events to the provider
    treeView.onDidChangeCheckboxState(e => {
        for (const [node, state] of e.items) {
            smellsProvider.handleCheckboxChange(node as any, state);
        }
    });

    // --- E3-S3: stream live fix progress via SSE ---
    async function runFix(workspace: string, selected: ReturnType<SmellsProvider['getSelectedSmells']>): Promise<void> {
        outputChannel.appendLine(`[ReactRefactor] Fixing ${selected.length} smell(s)…`);

        for (const s of selected) { smellsProvider.setFixStatus(s.smell_id, 'queued'); }
        statusBar.text = `$(sync~spin) Fixing ${selected.length} smell(s)…`;

        try {
            const fixRes = await fetch(`http://localhost:${SERVER_PORT}/fix`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace, smells: selected }),
            });
            if (!fixRes.ok) {
                throw new Error(`Server returned ${fixRes.status}: ${await fixRes.text()}`);
            }
            const { job_id } = await fixRes.json() as { job_id: string; total_tasks: number };
            outputChannel.appendLine(`[ReactRefactor] Job started: ${job_id}`);

            const progRes = await fetch(`http://localhost:${SERVER_PORT}/progress/${job_id}`);
            if (!progRes.ok || !progRes.body) {
                throw new Error(`Progress stream failed: ${progRes.status}`);
            }

            const reader = progRes.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            outer: while (true) {
                const { done, value } = await reader.read();
                if (done) { break; }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() ?? '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) { continue; }
                    const raw = line.slice(6).trim();
                    if (!raw || raw === '{"type": "ping"}') { continue; }

                    let event: Record<string, unknown>;
                    try { event = JSON.parse(raw); } catch { continue; }

                    if (event.type === 'node_done') {
                        smellsProvider.setFixStatus(event.smell_id as string, 'running');
                        outputChannel.appendLine(`  node: ${event.node}  (${event.smell_id})`);
                    } else if (event.type === 'task_done') {
                        smellsProvider.setFixStatus(event.smell_id as string, event.status as FixStatus);
                        outputChannel.appendLine(`  task done: ${event.smell_id} → ${event.status} (retries=${event.retry_count})`);
                    } else if (event.type === 'run_complete') {
                        const s = event.summary as Record<string, number>;
                        outputChannel.appendLine(`[ReactRefactor] Run complete — accepted:${s.accepted} rejected:${s.rejected} skipped:${s.skipped} failed:${s.failed}`);
                        vscode.window.showInformationMessage(
                            `ReactRefactor: ${s.accepted} fixed, ${s.rejected} rejected, ${s.skipped} skipped`
                        );
                        break outer;
                    }
                }
            }
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            outputChannel.appendLine(`[ReactRefactor] Fix error: ${msg}`);
            vscode.window.showErrorMessage(`ReactRefactor fix failed: ${msg}`);
            smellsProvider.clearFixStatus();
        } finally {
            const count = smellsProvider.getSelectedCount();
            if (count === 0) {
                statusBar.text = '$(check) 0 smells selected';
            } else {
                const { timeStr, costStr } = getEstimates(count);
                statusBar.text = `$(check) ${count} selected · ${timeStr} · ${costStr}`;
            }
        }
    }

    // Fix Selected command — confirmation dialog with time + cost summary
    const fixSelectedCommand = vscode.commands.registerCommand('reactRefactor.fixSelected', async () => {
        const selected = smellsProvider.getSelectedSmells();
        if (selected.length === 0) { return; }

        const folders = vscode.workspace.workspaceFolders;
        if (!folders || folders.length === 0) {
            vscode.window.showWarningMessage('ReactRefactor: No workspace folder is open.');
            return;
        }

        const { timeStr, costStr } = getEstimates(selected.length);
        const answer = await vscode.window.showInformationMessage(
            `Fix ${selected.length} smell${selected.length !== 1 ? 's' : ''}?`,
            {
                modal: true,
                detail: `Estimated time: ${timeStr}\nEstimated cost: ${costStr}`,
            },
            'Fix Now',
        );

        if (answer !== 'Fix Now') { return; }

        await runFix(folders[0].uri.fsPath, selected);
    });
    context.subscriptions.push(fixSelectedCommand);

    // Open a file and highlight the smell's line range
    const openSmellCommand = vscode.commands.registerCommand(
        'reactRefactor.openSmell',
        async (filePath: string, lineStart: number, lineEnd: number) => {
            const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
            const editor = await vscode.window.showTextDocument(doc, { preserveFocus: false });
            const range = new vscode.Range(
                new vscode.Position(Math.max(0, lineStart - 1), 0),
                new vscode.Position(Math.max(0, lineEnd - 1), Number.MAX_SAFE_INTEGER),
            );
            editor.selection = new vscode.Selection(range.start, range.end);
            editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
        }
    );
    context.subscriptions.push(openSmellCommand);

    // Register the scan command
    const scanCommand = vscode.commands.registerCommand('reactRefactor.scanProject', async () => {
        const folders = vscode.workspace.workspaceFolders;
        if (!folders || folders.length === 0) {
            vscode.window.showWarningMessage('ReactRefactor: No workspace folder is open.');
            return;
        }
        await runScan(folders[0].uri.fsPath, smellsProvider, outputChannel);
    });
    context.subscriptions.push(scanCommand);

    // Step 1 — find Python (now returns PythonInfo with path + version)
    const pythonInfo = await detectPython(outputChannel, context);

    if (!pythonInfo) {
        vscode.window.showErrorMessage(
            'ReactRefactor requires Python 3.8+. Could not find a Python installation.',
            'Select Python Interpreter'
        ).then(selection => {
            if (selection === 'Select Python Interpreter') {
                vscode.commands.executeCommand('python.selectInterpreter');
            }
        });
        outputChannel.appendLine('[ReactRefactor] ERROR: Python not found. Extension inactive.');
        return;
    }

    if (pythonInfo.version.endsWith(':TOO_OLD')) {
        const found = pythonInfo.version.replace(':TOO_OLD', '');
        vscode.window.showErrorMessage(
            `ReactRefactor requires Python 3.8 or higher. Found: ${found}`,
            'Select Python Interpreter'
        ).then(selection => {
            if (selection === 'Select Python Interpreter') {
                vscode.commands.executeCommand('python.selectInterpreter');
            }
        });
        outputChannel.appendLine(`[ReactRefactor] ERROR: Python ${found} is too old. Extension inactive.`);
        return;
    }

    // Step 2 — ensure Python dependencies are installed
    const depsReady = await ensureDependencies(pythonInfo.path, outputChannel, context);
    if (!depsReady) {
        return;
    }

    // Step 3 — start the server
    const started = await startServer(pythonInfo.path, outputChannel, context.extensionPath);

    if (!started) {
        vscode.window.showErrorMessage(
            'ReactRefactor: Server failed to start. Check the ReactRefactor Output Channel for details.'
        );
        return;
    }

    vscode.window.showInformationMessage('ReactRefactor is ready.');
    outputChannel.show(true);
}

export function deactivate(): void {
    if (outputChannel) {
        stopServer(outputChannel);
        outputChannel.appendLine('[ReactRefactor] Deactivated.');
    }
}
