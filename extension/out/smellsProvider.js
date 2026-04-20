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
exports.SmellsProvider = exports.SERVER_PORT = void 0;
exports.runScan = runScan;
const path = __importStar(require("path"));
const vscode = __importStar(require("vscode"));
exports.SERVER_PORT = 7432;
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const SEVERITY_RANK = { high: 3, medium: 2, low: 1 };
function topSeverityOf(smells) {
    if (smells.some(s => s.severity === 'high')) {
        return 'high';
    }
    if (smells.some(s => s.severity === 'medium')) {
        return 'medium';
    }
    return 'low';
}
function severityThemeIcon(severity) {
    switch (severity) {
        case 'high': return new vscode.ThemeIcon('error', new vscode.ThemeColor('list.errorForeground'));
        case 'medium': return new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground'));
        default: return new vscode.ThemeIcon('info');
    }
}
function fixStatusIcon(status) {
    switch (status) {
        case 'running': return new vscode.ThemeIcon('loading~spin');
        case 'accepted': return new vscode.ThemeIcon('check', new vscode.ThemeColor('testing.iconPassed'));
        case 'rejected': return new vscode.ThemeIcon('x', new vscode.ThemeColor('testing.iconFailed'));
        case 'skipped': return new vscode.ThemeIcon('circle-slash');
        case 'failed': return new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground'));
        case 'reverted': return new vscode.ThemeIcon('history');
        default: return new vscode.ThemeIcon('circle-outline');
    }
}
// ---------------------------------------------------------------------------
// SmellsProvider
// ---------------------------------------------------------------------------
class SmellsProvider {
    constructor() {
        this._onDidChangeTreeData = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._onDidChangeTreeData.event;
        /** Fires with the current selected count whenever checkboxes change. */
        this._onDidChangeSelection = new vscode.EventEmitter();
        this.onDidChangeSelection = this._onDidChangeSelection.event;
        this._smells = [];
        this._selected = new Set(); // smell_id
        this._fixStatus = new Map();
        this._fixErrors = new Map();
        this._fixRetries = new Map();
        this._fixScore = new Map();
        this._fixRejection = new Map(); // smell_id → rejection reason
        this._loading = false;
        this._error = null;
    }
    // --- state setters ---
    setLoading() {
        this._loading = true;
        this._error = null;
        this._onDidChangeTreeData.fire();
    }
    setSmells(smells) {
        this._loading = false;
        this._error = null;
        this._smells = smells;
        this._selected.clear();
        this._onDidChangeTreeData.fire();
        this._onDidChangeSelection.fire(0);
    }
    setError(msg) {
        this._loading = false;
        this._error = msg;
        this._onDidChangeTreeData.fire();
    }
    getSmells() { return this._smells; }
    getSelectedSmells() { return this._smells.filter(s => this._selected.has(s.smell_id)); }
    getSelectedCount() { return this._selected.size; }
    selectTopN(n) {
        const sorted = [...this._smells].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]);
        this._selected.clear();
        for (const smell of sorted.slice(0, n)) {
            this._selected.add(smell.smell_id);
        }
        this._onDidChangeTreeData.fire();
        this._onDidChangeSelection.fire(this._selected.size);
    }
    getFixResults() {
        return this._smells
            .filter(s => this._fixStatus.has(s.smell_id))
            .map(s => ({
            smell: s,
            status: this._fixStatus.get(s.smell_id),
            error: this._fixErrors.get(s.smell_id),
        }));
    }
    setFixStatus(smellId, status, error, retryCount, critiqueScore, rejectionReason) {
        this._fixStatus.set(smellId, status);
        if (error) {
            this._fixErrors.set(smellId, error);
        }
        if (retryCount !== undefined) {
            this._fixRetries.set(smellId, retryCount);
        }
        if (critiqueScore !== undefined) {
            this._fixScore.set(smellId, critiqueScore);
        }
        if (rejectionReason) {
            this._fixRejection.set(smellId, rejectionReason);
        }
        this._onDidChangeTreeData.fire();
    }
    clearFixStatus() {
        this._fixStatus.clear();
        this._fixErrors.clear();
        this._fixRetries.clear();
        this._fixScore.clear();
        this._fixRejection.clear();
        this._onDidChangeTreeData.fire();
    }
    // --- checkbox handling ---
    handleCheckboxChange(node, state) {
        const checked = state === vscode.TreeItemCheckboxState.Checked;
        if (node.kind === 'leaf') {
            checked
                ? this._selected.add(node.smell.smell_id)
                : this._selected.delete(node.smell.smell_id);
        }
        else if (node.kind === 'file') {
            for (const smell of node.smells) {
                checked
                    ? this._selected.add(smell.smell_id)
                    : this._selected.delete(smell.smell_id);
            }
        }
        this._onDidChangeTreeData.fire();
        this._onDidChangeSelection.fire(this._selected.size);
    }
    // --- TreeDataProvider ---
    getTreeItem(node) {
        if (node.kind === 'status') {
            const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.None);
            if (node.icon) {
                item.iconPath = new vscode.ThemeIcon(node.icon);
            }
            return item;
        }
        if (node.kind === 'file') {
            const filename = node.filePath.split(/[\\/]/).pop() ?? node.filePath;
            const item = new vscode.TreeItem(filename, vscode.TreeItemCollapsibleState.Expanded);
            item.description = `${node.smells.length} smell${node.smells.length !== 1 ? 's' : ''}`;
            item.tooltip = new vscode.MarkdownString(`**${node.filePath}**\n\n${node.smells.length} smell(s) — highest severity: **${node.topSeverity}**`);
            const anyRunning = node.smells.some(s => this._fixStatus.get(s.smell_id) === 'running' || this._fixStatus.get(s.smell_id) === 'queued');
            item.iconPath = anyRunning ? new vscode.ThemeIcon('loading~spin') : severityThemeIcon(node.topSeverity);
            item.contextValue = 'smellFile';
            item.command = {
                command: 'vscode.open',
                title: 'Open File',
                arguments: [vscode.Uri.file(node.filePath)],
            };
            const allChecked = node.smells.every(s => this._selected.has(s.smell_id));
            item.checkboxState = allChecked
                ? vscode.TreeItemCheckboxState.Checked
                : vscode.TreeItemCheckboxState.Unchecked;
            return item;
        }
        // leaf node
        const { smell } = node;
        const label = smell.component_name
            ? `${smell.component_name} — ${smell.smell_type}`
            : smell.smell_type;
        const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
        item.description = `L${smell.line_start}–${smell.line_end}`;
        const fs = this._fixStatus.get(smell.smell_id);
        let tooltipText = `**${smell.smell_type}**\n\n` +
            `Component: ${smell.component_name ?? '—'}\n\n` +
            `Lines: ${smell.line_start}–${smell.line_end}\n\n` +
            `Severity: **${smell.severity}**`;
        if (fs && fs !== 'queued' && fs !== 'running') {
            tooltipText += `\n\n---\n\nFix result: **${fs}**`;
            const retries = this._fixRetries.get(smell.smell_id);
            if (retries !== undefined && retries > 0) {
                tooltipText += ` (${retries} retr${retries === 1 ? 'y' : 'ies'})`;
            }
            const score = this._fixScore.get(smell.smell_id);
            if (score !== undefined && score !== null) {
                tooltipText += `\n\nCritique score: ${score}`;
            }
            const err = this._fixErrors.get(smell.smell_id);
            if (err) {
                tooltipText += `\n\nError: \`${err}\``;
            }
            const rejection = this._fixRejection.get(smell.smell_id);
            if (rejection) {
                tooltipText += `\n\n**Why rejected:**\n\`\`\`\n${rejection}\n\`\`\``;
            }
            else if (fs === 'rejected') {
                tooltipText += `\n\n*The pipeline could not produce a fix that passed code review after ${retries ?? 0} attempt(s).*`;
            }
        }
        item.tooltip = new vscode.MarkdownString(tooltipText);
        item.iconPath = fs ? fixStatusIcon(fs) : severityThemeIcon(smell.severity);
        item.checkboxState = this._selected.has(smell.smell_id)
            ? vscode.TreeItemCheckboxState.Checked
            : vscode.TreeItemCheckboxState.Unchecked;
        item.contextValue = fs ? `smellLeaf-${fs}` : 'smellLeaf';
        if (fs === 'accepted' || fs === 'rejected' || fs === 'skipped' || fs === 'failed') {
            item.command = {
                command: 'reactRefactor.viewDiff',
                title: 'View Diff',
                arguments: [smell, fs],
            };
        }
        else {
            item.command = {
                command: 'reactRefactor.openSmell',
                title: 'Go to smell',
                arguments: [smell.file_path, smell.line_start, smell.line_end],
            };
        }
        return item;
    }
    getChildren(node) {
        if (this._loading) {
            return [{ kind: 'status', label: 'Scanning…', icon: 'loading~spin' }];
        }
        if (this._error) {
            return [{ kind: 'status', label: `Error: ${this._error}`, icon: 'error' }];
        }
        if (!node) {
            // Root level — build and sort file nodes
            if (this._smells.length === 0) {
                return [{ kind: 'status', label: 'No smells detected. Click Scan to start.', icon: 'search' }];
            }
            const byFile = new Map();
            for (const smell of this._smells) {
                const list = byFile.get(smell.file_path) ?? [];
                list.push(smell);
                byFile.set(smell.file_path, list);
            }
            const fileNodes = [];
            for (const [filePath, smells] of byFile) {
                fileNodes.push({ kind: 'file', filePath, smells, topSeverity: topSeverityOf(smells) });
            }
            // Sort: severity desc, then smell count desc
            fileNodes.sort((a, b) => {
                const sevDiff = SEVERITY_RANK[b.topSeverity] - SEVERITY_RANK[a.topSeverity];
                return sevDiff !== 0 ? sevDiff : b.smells.length - a.smells.length;
            });
            return fileNodes;
        }
        if (node.kind === 'file') {
            return node.smells.map(smell => ({ kind: 'leaf', smell }));
        }
        return [];
    }
}
exports.SmellsProvider = SmellsProvider;
// ---------------------------------------------------------------------------
// Scan runner
// ---------------------------------------------------------------------------
async function runScan(workspace, provider, outputChannel) {
    provider.setLoading();
    outputChannel.appendLine(`[ReactRefactor] Scanning workspace: ${workspace}`);
    try {
        const response = await fetch(`http://localhost:${exports.SERVER_PORT}/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workspace }),
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Server returned ${response.status}: ${text}`);
        }
        const data = await response.json();
        // Resolve relative file_path values against the workspace root
        const smells = data.smells.map(s => ({
            ...s,
            file_path: path.isAbsolute(s.file_path)
                ? s.file_path
                : path.join(workspace, s.file_path),
        }));
        provider.setSmells(smells);
        outputChannel.appendLine(`[ReactRefactor] Scan complete — ${data.total} smell(s) in ${data.scan_duration_s}s`);
        const byTypeSummary = Object.entries(data.by_type)
            .map(([t, n]) => `${t}: ${n}`)
            .join(', ');
        outputChannel.appendLine(`[ReactRefactor] ${byTypeSummary}`);
    }
    catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        provider.setError(msg);
        outputChannel.appendLine(`[ReactRefactor] Scan error: ${msg}`);
        vscode.window.showErrorMessage(`ReactRefactor scan failed: ${msg}`);
    }
}
//# sourceMappingURL=smellsProvider.js.map