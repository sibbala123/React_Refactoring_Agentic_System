import * as path from 'path';
import * as vscode from 'vscode';

export const SERVER_PORT = 7432;

export type FixStatus = 'queued' | 'running' | 'accepted' | 'rejected' | 'skipped' | 'failed' | 'reverted';

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

export interface SmellItem {
    smell_id: string;
    smell_type: string;
    component_name: string | null;
    file_path: string;        // absolute path after runScan resolves it
    line_start: number;
    line_end: number;
    severity: 'high' | 'medium' | 'low';
    detector_metadata?: Record<string, unknown>;
}

/** Root-level node: one entry per file that has smells, sorted by severity then count. */
interface FileNode {
    kind: 'file';
    filePath: string;          // absolute
    smells: SmellItem[];
    topSeverity: 'high' | 'medium' | 'low';
}

/** Leaf node: a single smell entry under a file. */
interface LeafNode {
    kind: 'leaf';
    smell: SmellItem;
}

/** Placeholder node used for loading / empty / error states. */
interface StatusNode {
    kind: 'status';
    label: string;
    icon?: string;             // codicon id, e.g. 'loading~spin'
}

export type SmellNode = FileNode | LeafNode | StatusNode;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SEVERITY_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };

function topSeverityOf(smells: SmellItem[]): 'high' | 'medium' | 'low' {
    if (smells.some(s => s.severity === 'high')) { return 'high'; }
    if (smells.some(s => s.severity === 'medium')) { return 'medium'; }
    return 'low';
}

function severityThemeIcon(severity: 'high' | 'medium' | 'low'): vscode.ThemeIcon {
    switch (severity) {
        case 'high':   return new vscode.ThemeIcon('error',   new vscode.ThemeColor('list.errorForeground'));
        case 'medium': return new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground'));
        default:       return new vscode.ThemeIcon('info');
    }
}

function fixStatusIcon(status: FixStatus): vscode.ThemeIcon {
    switch (status) {
        case 'running':  return new vscode.ThemeIcon('loading~spin');
        case 'accepted': return new vscode.ThemeIcon('check', new vscode.ThemeColor('testing.iconPassed'));
        case 'rejected': return new vscode.ThemeIcon('x',     new vscode.ThemeColor('testing.iconFailed'));
        case 'skipped':  return new vscode.ThemeIcon('circle-slash');
        case 'failed':   return new vscode.ThemeIcon('warning', new vscode.ThemeColor('list.warningForeground'));
        case 'reverted': return new vscode.ThemeIcon('history');
        default:         return new vscode.ThemeIcon('circle-outline');
    }
}

// ---------------------------------------------------------------------------
// SmellsProvider
// ---------------------------------------------------------------------------

export class SmellsProvider implements vscode.TreeDataProvider<SmellNode> {
    private readonly _onDidChangeTreeData =
        new vscode.EventEmitter<SmellNode | undefined | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    /** Fires with the current selected count whenever checkboxes change. */
    private readonly _onDidChangeSelection = new vscode.EventEmitter<number>();
    readonly onDidChangeSelection = this._onDidChangeSelection.event;

    private _smells: SmellItem[] = [];
    private _selected = new Set<string>(); // smell_id
    private _fixStatus = new Map<string, FixStatus>(); // smell_id → fix status
    private _fixErrors = new Map<string, string>(); // smell_id → error message
    private _loading = false;
    private _error: string | null = null;

    // --- state setters ---

    setLoading(): void {
        this._loading = true;
        this._error = null;
        this._onDidChangeTreeData.fire();
    }

    setSmells(smells: SmellItem[]): void {
        this._loading = false;
        this._error = null;
        this._smells = smells;
        this._selected.clear();
        this._onDidChangeTreeData.fire();
        this._onDidChangeSelection.fire(0);
    }

    setError(msg: string): void {
        this._loading = false;
        this._error = msg;
        this._onDidChangeTreeData.fire();
    }

    getSmells(): SmellItem[] { return this._smells; }
    getSelectedSmells(): SmellItem[] { return this._smells.filter(s => this._selected.has(s.smell_id)); }
    getSelectedCount(): number { return this._selected.size; }

    selectTopN(n: number): void {
        const sorted = [...this._smells].sort((a, b) =>
            SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]
        );
        this._selected.clear();
        for (const smell of sorted.slice(0, n)) {
            this._selected.add(smell.smell_id);
        }
        this._onDidChangeTreeData.fire();
        this._onDidChangeSelection.fire(this._selected.size);
    }
    getFixResults(): { smell: SmellItem; status: FixStatus; error?: string }[] {
        return this._smells
            .filter(s => this._fixStatus.has(s.smell_id))
            .map(s => ({
                smell: s,
                status: this._fixStatus.get(s.smell_id)!,
                error: this._fixErrors.get(s.smell_id),
            }));
    }

    setFixStatus(smellId: string, status: FixStatus, error?: string): void {
        this._fixStatus.set(smellId, status);
        if (error) { this._fixErrors.set(smellId, error); }
        this._onDidChangeTreeData.fire();
    }

    clearFixStatus(): void {
        this._fixStatus.clear();
        this._fixErrors.clear();
        this._onDidChangeTreeData.fire();
    }

    // --- checkbox handling ---

    handleCheckboxChange(node: SmellNode, state: vscode.TreeItemCheckboxState): void {
        const checked = state === vscode.TreeItemCheckboxState.Checked;

        if (node.kind === 'leaf') {
            checked
                ? this._selected.add(node.smell.smell_id)
                : this._selected.delete(node.smell.smell_id);
        } else if (node.kind === 'file') {
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

    getTreeItem(node: SmellNode): vscode.TreeItem {
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
            item.tooltip = new vscode.MarkdownString(
                `**${node.filePath}**\n\n${node.smells.length} smell(s) — highest severity: **${node.topSeverity}**`
            );
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
        item.tooltip = new vscode.MarkdownString(
            `**${smell.smell_type}**\n\n` +
            `Component: ${smell.component_name ?? '—'}\n\n` +
            `Lines: ${smell.line_start}–${smell.line_end}\n\n` +
            `Severity: **${smell.severity}**`
        );
        const fs = this._fixStatus.get(smell.smell_id);
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
        } else {
            item.command = {
                command: 'reactRefactor.openSmell',
                title: 'Go to smell',
                arguments: [smell.file_path, smell.line_start, smell.line_end],
            };
        }
        return item;
    }

    getChildren(node?: SmellNode): SmellNode[] {
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

            const byFile = new Map<string, SmellItem[]>();
            for (const smell of this._smells) {
                const list = byFile.get(smell.file_path) ?? [];
                list.push(smell);
                byFile.set(smell.file_path, list);
            }

            const fileNodes: FileNode[] = [];
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
            return node.smells.map(smell => ({ kind: 'leaf' as const, smell }));
        }

        return [];
    }
}

// ---------------------------------------------------------------------------
// Scan runner
// ---------------------------------------------------------------------------

export async function runScan(
    workspace: string,
    provider: SmellsProvider,
    outputChannel: vscode.OutputChannel,
): Promise<void> {
    provider.setLoading();
    outputChannel.appendLine(`[ReactRefactor] Scanning workspace: ${workspace}`);

    try {
        const response = await fetch(`http://localhost:${SERVER_PORT}/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workspace }),
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Server returned ${response.status}: ${text}`);
        }

        const data = await response.json() as {
            total: number;
            scan_duration_s: number;
            by_type: Record<string, number>;
            smells: (Omit<SmellItem, 'file_path'> & { file_path: string })[];
        };

        // Resolve relative file_path values against the workspace root
        const smells: SmellItem[] = data.smells.map(s => ({
            ...s,
            file_path: path.isAbsolute(s.file_path)
                ? s.file_path
                : path.join(workspace, s.file_path),
        }));

        provider.setSmells(smells);

        outputChannel.appendLine(
            `[ReactRefactor] Scan complete — ${data.total} smell(s) in ${data.scan_duration_s}s`,
        );
        const byTypeSummary = Object.entries(data.by_type)
            .map(([t, n]) => `${t}: ${n}`)
            .join(', ');
        outputChannel.appendLine(`[ReactRefactor] ${byTypeSummary}`);
    } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        provider.setError(msg);
        outputChannel.appendLine(`[ReactRefactor] Scan error: ${msg}`);
        vscode.window.showErrorMessage(`ReactRefactor scan failed: ${msg}`);
    }
}
