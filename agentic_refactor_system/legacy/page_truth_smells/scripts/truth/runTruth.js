import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { getCliArg, readRoutesConfig } from './helpers.js'
import { runTruthGeneration } from './generateTruth.js'

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

async function run() {
  const outArg = getCliArg('--out')
  const outputDir = outArg || 'truth'
  const { baseUrl } = await readRoutesConfig(process.cwd())
  const alreadyUp = await isUrlReachable(baseUrl)

  if (alreadyUp) {
    console.log(`Using existing dev server: ${baseUrl}`)
    await runTruthGeneration(outputDir)
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
    await runTruthGeneration(outputDir)
  } finally {
    devProc.kill()
  }
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
