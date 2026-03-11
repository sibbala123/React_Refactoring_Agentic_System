import fs from 'node:fs/promises'
import path from 'node:path'

export const TRUTH_VERSION = 'page-truth-v1'
export const FIXED_ENV = {
  browser: 'chromium',
  viewport: { width: 1280, height: 720 },
  deviceScaleFactor: 1,
}

export async function readRoutesConfig(cwd = process.cwd()) {
  const configPath = path.join(cwd, 'truth.routes.json')
  const raw = await fs.readFile(configPath, 'utf8')
  const parsed = JSON.parse(raw)
  if (!parsed.baseUrl || !Array.isArray(parsed.routes)) {
    throw new Error('truth.routes.json must include baseUrl and routes[]')
  }
  return parsed
}

export function sanitizeRoutePath(routePath) {
  if (routePath === '/') return 'home'
  const cleaned = routePath.replace(/^\//, '').replace(/[^\w-]+/g, '-')
  return cleaned || 'route'
}

export function outputFileName(routePath, stateName) {
  return `truth__${sanitizeRoutePath(routePath)}__${stateName}.json`
}

export async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true })
}

export async function writeJson(filePath, data) {
  await fs.writeFile(filePath, `${JSON.stringify(data, null, 2)}\n`, 'utf8')
}

export function getCliArg(flag, argv = process.argv.slice(2)) {
  const index = argv.indexOf(flag)
  if (index === -1) return ''
  return argv[index + 1] || ''
}

export function resolveOutputDir(outArg, cwd = process.cwd()) {
  const dir = outArg && outArg.trim() ? outArg.trim() : 'truth'
  return path.isAbsolute(dir) ? dir : path.join(cwd, dir)
}
