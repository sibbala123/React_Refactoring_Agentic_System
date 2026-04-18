/**
 * Pre-package bundle script — copies runtime files from project root into
 * the extension directory so they are included in the VSIX.
 *
 * Copies: server/  vendor/  agentic_refactor_system/  requirements.txt
 */

const fs   = require('fs');
const path = require('path');

const EXT_ROOT     = path.resolve(__dirname, '..');
const PROJECT_ROOT = path.resolve(EXT_ROOT, '..');

const COPIES = [
    { src: 'server',                    dest: 'server' },
    { src: 'vendor',                    dest: 'vendor' },
    { src: 'agentic_refactor_system',   dest: 'agentic_refactor_system' },
    { src: 'requirements.txt',          dest: 'requirements.txt' },
];

const EXCLUDE_DIRS = new Set(['runs', '__pycache__', '.git', 'node_modules', '.pytest_cache']);

// Paths (relative to PROJECT_ROOT) whose node_modules must be included because
// the tool won't run without them in a bundled/installed context.
const INCLUDE_NODE_MODULES = new Set([
    path.join('vendor', 'reactsniffer'),
]);

function copyRecursive(src, dest, relFromProject = '') {
    const stat = fs.statSync(src);
    if (stat.isDirectory()) {
        fs.mkdirSync(dest, { recursive: true });
        for (const entry of fs.readdirSync(src)) {
            const childRel = relFromProject ? path.join(relFromProject, entry) : entry;
            if (EXCLUDE_DIRS.has(entry)) {
                // Allow node_modules for explicitly whitelisted parent paths
                if (entry === 'node_modules' && INCLUDE_NODE_MODULES.has(relFromProject)) {
                    // fall through to copy
                } else {
                    continue;
                }
            }
            copyRecursive(path.join(src, entry), path.join(dest, entry), childRel);
        }
    } else {
        fs.copyFileSync(src, dest);
    }
}

let ok = true;
for (const { src, dest } of COPIES) {
    const srcPath  = path.join(PROJECT_ROOT, src);
    const destPath = path.join(EXT_ROOT, dest);

    if (!fs.existsSync(srcPath)) {
        console.warn(`[bundle] WARNING: source not found, skipping: ${srcPath}`);
        continue;
    }

    console.log(`[bundle] Copying ${src} → extension/${dest}`);
    try {
        copyRecursive(srcPath, destPath, src);
    } catch (err) {
        console.error(`[bundle] ERROR copying ${src}: ${err.message}`);
        ok = false;
    }
}

if (!ok) { process.exit(1); }
console.log('[bundle] Done.');
