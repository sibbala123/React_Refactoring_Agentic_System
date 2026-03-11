import path from 'node:path'
import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { runTruthGeneration } from '../truth/generateTruth.js'
import { ensureDir, getCliArg, readRoutesConfig, resolveOutputDir, writeJson } from '../truth/helpers.js'
import { runDomCapture } from './captureDom.js'
import { runScreenCapture } from './captureScreens.js'

function getNpmCommand() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm'
}

async function isUrlReachable(url) {
  try {
    const response = await fetch(url, { method: 'GET' })
    return response.ok
  } catch {
    return false
  }
}

async function waitForUrl(url, timeoutMs) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await isUrlReachable(url)) return true
    await delay(500)
  }
  return false
}

async function runCaptureSet(outArg = 'artifacts') {
  const cwd = process.cwd()
  const { baseUrl, routes } = await readRoutesConfig(cwd)
  const outRoot = resolveOutputDir(outArg, cwd)
  await ensureDir(outRoot)

  const truthDir = path.join(outRoot, 'truth')
  const domDir = path.join(outRoot, 'dom')
  const screensDir = path.join(outRoot, 'screens')
  await Promise.all([ensureDir(truthDir), ensureDir(domDir), ensureDir(screensDir)])

  const truthFiles = await runTruthGeneration(truthDir)
  const domFiles = await runDomCapture(domDir)
  const screenFiles = await runScreenCapture(screensDir)

  const routeStates = routes.flatMap((route) => {
    const states = Array.isArray(route.states) && route.states.length ? route.states : [{ name: 'default', steps: [] }]
    return states.map((state) => ({ route: route.path, state: state.name }))
  })

  await writeJson(path.join(outRoot, 'index.json'), {
    generatedAt: new Date().toISOString(),
    baseUrl,
    outDir: outRoot,
    routeStates,
    files: {
      truth: truthFiles,
      dom: domFiles,
      screens: screenFiles,
    },
  })
}

async function run() {
  const outArg = getCliArg('--out') || 'artifacts'
  const { baseUrl } = await readRoutesConfig(process.cwd())
  const alreadyUp = await isUrlReachable(baseUrl)

  if (alreadyUp) {
    console.log(`Using existing dev server: ${baseUrl}`)
    await runCaptureSet(outArg)
    return
  }

  const npmCmd = getNpmCommand()
  const devProc = spawn(npmCmd, ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], {
    stdio: 'inherit',
    shell: true,
  })

  try {
    const ready = await waitForUrl(baseUrl, 30000)
    if (!ready) {
      throw new Error(`Timed out waiting for ${baseUrl}`)
    }
    await runCaptureSet(outArg)
  } finally {
    devProc.kill()
  }
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
