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
exports.detectPython = detectPython;
exports.startServer = startServer;
exports.stopServer = stopServer;
exports.isServerRunning = isServerRunning;
const vscode = __importStar(require("vscode"));
const cp = __importStar(require("child_process"));
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const SERVER_PORT = 7432;
const SERVER_START_TIMEOUT_MS = 5000;
const HEALTH_URL = `http://localhost:${SERVER_PORT}/health`;
const PYTHON_PATH_KEY = 'reactRefactor.pythonPath';
const MIN_PYTHON_VERSION = [3, 8];
let serverProcess = null;
/**
 * Parses "Python 3.11.2" or "Python 3.11.2 ..." into [3, 11, 2].
 * Returns null if the string doesn't match.
 */
function parseVersion(raw) {
    const match = raw.match(/Python\s+(\d+)\.(\d+)\.(\d+)/i);
    if (!match) {
        return null;
    }
    return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
}
/**
 * Returns true if version tuple satisfies >= MIN_PYTHON_VERSION.
 */
function isSupportedVersion(version) {
    for (let i = 0; i < MIN_PYTHON_VERSION.length; i++) {
        if (version[i] > MIN_PYTHON_VERSION[i]) {
            return true;
        }
        if (version[i] < MIN_PYTHON_VERSION[i]) {
            return false;
        }
    }
    return true;
}
/**
 * Runs `<pythonPath> --version` and returns PythonInfo if version >= 3.8,
 * or null if the executable is missing or the version is too old.
 */
function probePython(pythonPath, outputChannel) {
    try {
        const result = cp.spawnSync(pythonPath, ['--version'], { encoding: 'utf8' });
        if (result.status !== 0) {
            return null;
        }
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
    }
    catch {
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
async function detectPython(outputChannel, context) {
    // 1. Check cached path from previous activation
    const cached = context.globalState.get(PYTHON_PATH_KEY);
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
    let tooOldInfo = null;
    for (const cmd of candidates) {
        const info = probePython(cmd, outputChannel);
        if (!info) {
            continue;
        }
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
function resolveProjectPath(extensionPath, ...segments) {
    const bundled = path.join(extensionPath, ...segments);
    if (fs.existsSync(bundled)) {
        return bundled;
    }
    return path.join(extensionPath, '..', ...segments);
}
async function startServer(pythonPath, outputChannel, extensionPath) {
    const serverScript = resolveProjectPath(extensionPath, 'server', 'app.py');
    const serverCwd = path.dirname(path.dirname(serverScript)); // project root
    if (!fs.existsSync(serverScript)) {
        outputChannel.appendLine(`[ReactRefactor] ERROR: server/app.py not found at ${serverScript}`);
        return false;
    }
    outputChannel.appendLine(`[ReactRefactor] Starting server: ${pythonPath} ${serverScript}`);
    const apiKey = vscode.workspace.getConfiguration('reactRefactor').get('openaiApiKey') ?? '';
    const env = { ...process.env };
    if (apiKey) {
        env['OPENAI_API_KEY'] = apiKey;
    }
    serverProcess = cp.spawn(pythonPath, [serverScript, '--port', String(SERVER_PORT)], {
        cwd: serverCwd,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
    });
    serverProcess.stdout?.on('data', (data) => {
        outputChannel.appendLine(`[server] ${data.toString().trim()}`);
    });
    serverProcess.stderr?.on('data', (data) => {
        outputChannel.appendLine(`[server] ${data.toString().trim()}`);
    });
    serverProcess.on('exit', (code) => {
        outputChannel.appendLine(`[ReactRefactor] Server exited with code ${code}`);
        serverProcess = null;
    });
    // Wait until /health responds or timeout
    return await waitForServer(outputChannel);
}
/**
 * Polls /health every 250ms until it responds or timeout is reached.
 */
async function waitForServer(outputChannel) {
    const deadline = Date.now() + SERVER_START_TIMEOUT_MS;
    while (Date.now() < deadline) {
        try {
            const response = await fetch(HEALTH_URL);
            if (response.ok) {
                const body = await response.json();
                outputChannel.appendLine(`[ReactRefactor] Server ready — version ${body.version}`);
                return true;
            }
        }
        catch {
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
function stopServer(outputChannel) {
    if (serverProcess) {
        outputChannel.appendLine('[ReactRefactor] Stopping server...');
        serverProcess.kill();
        serverProcess = null;
    }
}
function isServerRunning() {
    return serverProcess !== null && !serverProcess.killed;
}
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
//# sourceMappingURL=serverManager.js.map