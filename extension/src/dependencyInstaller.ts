import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

const DEPS_INSTALLED_KEY = 'reactRefactor.depsInstalled';

/**
 * Ensures Python dependencies are installed before the server starts.
 *
 * - First activation:  runs `python -m pip install -r requirements.txt`,
 *                      shows status bar progress, stores success in globalState.
 * - Later activations: skips install (reads flag from globalState).
 * - On failure:        shows error notification with manual install command.
 *
 * Returns true if deps are ready, false if install failed.
 */
export async function ensureDependencies(
    pythonPath: string,
    outputChannel: vscode.OutputChannel,
    context: vscode.ExtensionContext
): Promise<boolean> {
    // Already installed on a previous activation — skip
    if (context.globalState.get<boolean>(DEPS_INSTALLED_KEY)) {
        outputChannel.appendLine('[ReactRefactor] Dependencies already installed, skipping.');
        return true;
    }

    outputChannel.appendLine('[ReactRefactor] First run — installing dependencies...');
    outputChannel.show(true);

    // Status bar item so user knows something is happening
    const statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    statusItem.text = '$(sync~spin) ReactRefactor: Setting up...';
    statusItem.tooltip = 'Installing Python dependencies for ReactRefactor';
    statusItem.show();

    const bundled = path.join(context.extensionPath, 'requirements.txt');
    const requirementsPath = require('fs').existsSync(bundled)
        ? bundled
        : path.join(context.extensionPath, '..', 'requirements.txt');

    try {
        const success = await runPipInstall(pythonPath, requirementsPath, outputChannel);

        if (success) {
            await context.globalState.update(DEPS_INSTALLED_KEY, true);
            outputChannel.appendLine('[ReactRefactor] Dependencies installed successfully.');
            statusItem.dispose();
            return true;
        } else {
            showInstallError(requirementsPath, outputChannel);
            statusItem.dispose();
            return false;
        }
    } catch (err) {
        outputChannel.appendLine(`[ReactRefactor] Unexpected error during install: ${err}`);
        showInstallError(requirementsPath, outputChannel);
        statusItem.dispose();
        return false;
    }
}

/**
 * Runs `python -m pip install -r <requirementsPath>` and streams
 * output to the Output Channel line by line.
 *
 * Returns true on exit code 0, false otherwise.
 */
function runPipInstall(
    pythonPath: string,
    requirementsPath: string,
    outputChannel: vscode.OutputChannel
): Promise<boolean> {
    return new Promise((resolve) => {
        const proc = cp.spawn(
            pythonPath,
            ['-m', 'pip', 'install', '-r', requirementsPath, '--quiet'],
            { stdio: ['ignore', 'pipe', 'pipe'] }
        );

        proc.stdout?.on('data', (data: Buffer) => {
            const lines = data.toString().trim().split('\n');
            lines.forEach(line => {
                if (line.trim()) {
                    outputChannel.appendLine(`[pip] ${line}`);
                }
            });
        });

        proc.stderr?.on('data', (data: Buffer) => {
            const lines = data.toString().trim().split('\n');
            lines.forEach(line => {
                if (line.trim()) {
                    outputChannel.appendLine(`[pip] ${line}`);
                }
            });
        });

        proc.on('exit', (code: number | null) => {
            resolve(code === 0);
        });

        proc.on('error', () => {
            resolve(false);
        });
    });
}

/**
 * Shows an error notification with the manual install command.
 */
function showInstallError(requirementsPath: string, outputChannel: vscode.OutputChannel): void {
    const manualCmd = `pip install -r "${requirementsPath}"`;
    outputChannel.appendLine(`[ReactRefactor] ERROR: Dependency install failed.`);
    outputChannel.appendLine(`[ReactRefactor] Run manually: ${manualCmd}`);

    vscode.window.showErrorMessage(
        'ReactRefactor: Failed to install Python dependencies.',
        'Show Output',
        'Copy Install Command'
    ).then(selection => {
        if (selection === 'Show Output') {
            outputChannel.show(true);
        } else if (selection === 'Copy Install Command') {
            vscode.env.clipboard.writeText(manualCmd);
            vscode.window.showInformationMessage('Install command copied to clipboard.');
        }
    });
}
