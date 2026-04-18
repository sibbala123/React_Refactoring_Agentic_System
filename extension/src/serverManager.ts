import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

const SERVER_PORT = 7432;
const SERVER_START_TIMEOUT_MS = 5000;
const HEALTH_URL = `http://localhost:${SERVER_PORT}/health`;
const PYTHON_PATH_KEY = 'reactRefactor.pythonPath';
const MIN_PYTHON_VERSION = [3, 8];

let serverProcess: cp.ChildProcess | null = null;

export interface PythonInfo {
    path: string;
    version: string; // e.g. "3.11.2"
}

/**
 * Parses "Python 3.11.2" or "Python 3.11.2 ..." into [3, 11, 2].
 * Returns null if the string doesn't match.
 */
function parseVersion(raw: string): number[] | null {
    const match = raw.match(/Python\s+(\d+)\.(\d+)\.(\d+)/i);
    if (!match) { return null; }
    return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
}

/**
 * Returns true if version tuple satisfies >= MIN_PYTHON_VERSION.
 */
function isSupportedVersion(version: number[]): boolean {
    for (let i = 0; i < MIN_PYTHON_VERSION.length; i++) {
        if (version[i] > MIN_PYTHON_VERSION[i]) { return true; }
        if (version[i] < MIN_PYTHON_VERSION[i]) { return false; }
    }
    return true;
}

/**
 * Runs `<pythonPath> --version` and returns PythonInfo if version >= 3.8,
 * or null if the executable is missing or the version is too old.
 */
function probePython(
    pythonPath: string,
    outputChannel: vscode.OutputChannel
): PythonInfo | null {
    try {
        const result = cp.spawnSync(pythonPath, ['--version'], { encoding: 'utf8' });
        if (result.status !== 0) { return null; }

        // Python 3 prints to stdout; Python 2 prints to stderr
        const raw = (result.stdout || result.stderr || '').trim();
        const version = parseVersion(raw);

        if (!version) {
            outputChannel.appendLine(`[ReactRefactor] Could not parse version from: "${raw}"`);
            return null;
        }

        const versionStr = version.join('.');

        if (!isSupportedVersion(version)) {
            outputChannel.appendLine(`[ReactRefactor] Found Python ${versionStr} at ${pythonPath} — too old (need 3.8+)`);
            // Return a sentinel so the caller can show a specific error
            return { path: pythonPath, version: `${versionStr}:TOO_OLD` };
        }

        return { path: pythonPath, version: versionStr };
    } catch {
        return null;
    }
}

/**
 * Finds a usable Python 3.8+ executable.
 * Resolution order:
 *   1. Cached path in workspace state (skip re-detection on subsequent activations)
 *   2. ms-python extension API
 *   3. python3 / python on PATH
 *
 * Logs every step to the Output Channel.
 * Returns null if no suitable Python is found.
 */
export async function detectPython(
    outputChannel: vscode.OutputChannel,
    context: vscode.ExtensionContext
): Promise<PythonInfo | null> {
    // 1. Check cached path from previous activation
    const cached = context.globalState.get<string>(PYTHON_PATH_KEY);
    if (cached) {
        const info = probePython(cached, outputChannel);
        if (info && !info.version.endsWith(':TOO_OLD')) {
            outputChannel.appendLine(`[ReactRefactor] Using cached Python ${info.version} at ${info.path}`);
            return info;
        }
        // Cache is stale — clear it and fall through
        await context.globalState.update(PYTHON_PATH_KEY, undefined);
        outputChannel.appendLine(`[ReactRefactor] Cached Python path is no longer valid, re-detecting...`);
    }

    // 2. Try ms-python extension API
    const pythonExt = vscode.extensions.getExtension('ms-python.python');
    if (pythonExt) {
        if (!pythonExt.isActive) {
            await pythonExt.activate();
        }
        const extPath = pythonExt.exports?.settings?.getExecutionDetails?.()?.execCommand?.[0];
        if (extPath && fs.existsSync(extPath)) {
            const info = probePython(extPath, outputChannel);
            if (info && !info.version.endsWith(':TOO_OLD')) {
                outputChannel.appendLine(`[ReactRefactor] Using Python ${info.version} at ${info.path} (from ms-python)`);
                await context.globalState.update(PYTHON_PATH_KEY, info.path);
                return info;
            }
        }
    }

    // 3. Fall back to PATH candidates
    const candidates = process.platform === 'win32'
        ? ['python', 'python3']
        : ['python3', 'python'];

    let tooOldInfo: PythonInfo | null = null;

    for (const cmd of candidates) {
        const info = probePython(cmd, outputChannel);
        if (!info) { continue; }
        if (info.version.endsWith(':TOO_OLD')) {
            tooOldInfo = info; // remember for error message
            continue;
        }
        outputChannel.appendLine(`[ReactRefactor] Using Python ${info.version} at ${info.path}`);
        await context.globalState.update(PYTHON_PATH_KEY, info.path);
        return info;
    }

    // Nothing usable found — return too-old sentinel if we saw one, otherwise null
    return tooOldInfo;
}

/**
 * Spawns the FastAPI server and waits until /health responds.
 */
/**
 * Resolves a project-relative path, checking the bundled location inside the
 * extension first (VSIX install) then falling back to the sibling dev layout.
 */
function resolveProjectPath(extensionPath: string, ...segments: string[]): string {
    const bundled = path.join(extensionPath, ...segments);
    if (fs.existsSync(bundled)) { return bundled; }
    return path.join(extensionPath, '..', ...segments);
}

export async function startServer(
    pythonPath: string,
    outputChannel: vscode.OutputChannel,
    extensionPath: string
): Promise<boolean> {
    const serverScript = resolveProjectPath(extensionPath, 'server', 'app.py');
    const serverCwd    = path.dirname(path.dirname(serverScript)); // project root

    if (!fs.existsSync(serverScript)) {
        outputChannel.appendLine(`[ReactRefactor] ERROR: server/app.py not found at ${serverScript}`);
        return false;
    }

    outputChannel.appendLine(`[ReactRefactor] Starting server: ${pythonPath} ${serverScript}`);

    const apiKey = vscode.workspace.getConfiguration('reactRefactor').get<string>('openaiApiKey') ?? '';
    const env = { ...process.env };
    if (apiKey) { env['OPENAI_API_KEY'] = apiKey; }

    serverProcess = cp.spawn(pythonPath, [serverScript, '--port', String(SERVER_PORT)], {
        cwd: serverCwd,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
    });

    serverProcess.stdout?.on('data', (data: Buffer) => {
        outputChannel.appendLine(`[server] ${data.toString().trim()}`);
    });

    serverProcess.stderr?.on('data', (data: Buffer) => {
        outputChannel.appendLine(`[server] ${data.toString().trim()}`);
    });

    serverProcess.on('exit', (code: number | null) => {
        outputChannel.appendLine(`[ReactRefactor] Server exited with code ${code}`);
        serverProcess = null;
    });

    // Wait until /health responds or timeout
    return await waitForServer(outputChannel);
}

/**
 * Polls /health every 250ms until it responds or timeout is reached.
 */
async function waitForServer(outputChannel: vscode.OutputChannel): Promise<boolean> {
    const deadline = Date.now() + SERVER_START_TIMEOUT_MS;

    while (Date.now() < deadline) {
        try {
            const response = await fetch(HEALTH_URL);
            if (response.ok) {
                const body = await response.json() as { status: string; version: string };
                outputChannel.appendLine(`[ReactRefactor] Server ready — version ${body.version}`);
                return true;
            }
        } catch {
            // not ready yet
        }
        await sleep(250);
    }

    outputChannel.appendLine(`[ReactRefactor] ERROR: Server did not respond within ${SERVER_START_TIMEOUT_MS}ms`);
    return false;
}

/**
 * Kills the server process if it is running.
 */
export function stopServer(outputChannel: vscode.OutputChannel): void {
    if (serverProcess) {
        outputChannel.appendLine('[ReactRefactor] Stopping server...');
        serverProcess.kill();
        serverProcess = null;
    }
}

export function isServerRunning(): boolean {
    return serverProcess !== null && !serverProcess.killed;
}

function sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
}
