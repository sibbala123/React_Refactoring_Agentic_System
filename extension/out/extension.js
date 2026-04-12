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
const vscode = __importStar(require("vscode"));
const serverManager_1 = require("./serverManager");
const dependencyInstaller_1 = require("./dependencyInstaller");
let outputChannel;
async function activate(context) {
    outputChannel = vscode.window.createOutputChannel('ReactRefactor');
    outputChannel.appendLine('[ReactRefactor] Activating...');
    // Register the scan command (placeholder — wired up fully in E2-S2)
    const scanCommand = vscode.commands.registerCommand('reactRefactor.scanProject', () => {
        vscode.window.showInformationMessage('ReactRefactor: Scan not yet implemented. Come back in Sprint 2!');
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