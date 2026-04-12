import * as vscode from 'vscode';
import { detectPython, startServer, stopServer } from './serverManager';
import { ensureDependencies } from './dependencyInstaller';

let outputChannel: vscode.OutputChannel;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    outputChannel = vscode.window.createOutputChannel('ReactRefactor');
    outputChannel.appendLine('[ReactRefactor] Activating...');

    // Register the scan command (placeholder — wired up fully in E2-S2)
    const scanCommand = vscode.commands.registerCommand('reactRefactor.scanProject', () => {
        vscode.window.showInformationMessage('ReactRefactor: Scan not yet implemented. Come back in Sprint 2!');
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
