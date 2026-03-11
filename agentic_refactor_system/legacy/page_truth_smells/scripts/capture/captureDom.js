import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from 'playwright'
import {
  FIXED_ENV,
  ensureDir,
  getCliArg,
  outputFileName,
  readRoutesConfig,
  resolveOutputDir,
} from '../truth/helpers.js'
import fs from 'node:fs/promises'

const MOTION_RESET_CSS = `
*,
*::before,
*::after {
  animation: none !important;
  transition: none !important;
  scroll-behavior: auto !important;
}
`

function normalizeStep(step) {
  if (!step || typeof step !== 'object') {
    throw new Error(`Invalid step: ${JSON.stringify(step)}`)
  }
  if (step.type) return step
  for (const type of ['clickByRole', 'typeByPlaceholder', 'selectByLabelOrRole', 'waitForText']) {
    if (step[type]) return { type, ...step[type] }
  }
  throw new Error(`Unsupported step shape: ${JSON.stringify(step)}`)
}

async function runStep(page, rawStep) {
  const step = normalizeStep(rawStep)
  if (step.type === 'clickByRole') {
    await page.getByRole(step.role, { name: step.name }).click()
    return
  }
  if (step.type === 'typeByPlaceholder') {
    await page.getByPlaceholder(step.placeholder).fill(step.text ?? '')
    return
  }
  if (step.type === 'selectByLabelOrRole') {
    if (step.role) {
      await page.getByRole(step.role, { name: step.name }).selectOption(step.value)
      return
    }
    await page.getByLabel(step.name).selectOption(step.value)
    return
  }
  if (step.type === 'waitForText') {
    await page.getByText(step.text).first().waitFor({ state: 'visible' })
    return
  }
  throw new Error(`Unsupported step type: ${step.type}`)
}

async function runConfiguredSteps(page, steps) {
  for (const step of steps) {
    await runStep(page, step)
  }
}

function domFileName(routePath, stateName) {
  return outputFileName(routePath, stateName).replace(/^truth__/, 'dom__').replace(/\.json$/, '.html')
}

export async function runDomCapture(outDirArg = 'dom') {
  const cwd = process.cwd()
  const { baseUrl, routes } = await readRoutesConfig(cwd)
  const outputDir = resolveOutputDir(outDirArg, cwd)
  await ensureDir(outputDir)

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: FIXED_ENV.viewport,
    deviceScaleFactor: FIXED_ENV.deviceScaleFactor,
    reducedMotion: 'reduce',
  })

  const generated = []
  try {
    for (const route of routes) {
      const states = Array.isArray(route.states) && route.states.length ? route.states : [{ name: 'default', steps: [] }]
      for (const state of states) {
        const page = await context.newPage()
        await page.goto(`${baseUrl}${route.path}`, { waitUntil: 'networkidle' })
        await page.addStyleTag({ content: MOTION_RESET_CSS })
        await runConfiguredSteps(page, Array.isArray(state.steps) ? state.steps : [])

        const html = await page.evaluate(() => {
          const root = document.querySelector('#root')
          if (root && root.innerHTML) return root.innerHTML
          return document.documentElement.outerHTML
        })

        const fileName = domFileName(route.path, state.name)
        await fs.writeFile(path.join(outputDir, fileName), html, 'utf8')
        generated.push({ file: fileName, route: route.path, state: state.name, generatedAt: new Date().toISOString() })
        await page.close()
        console.log(`Generated ${fileName}`)
      }
    }
  } finally {
    await context.close()
    await browser.close()
  }

  return generated
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const outArg = getCliArg('--out')
  runDomCapture(outArg || 'dom').catch((err) => {
    console.error(err)
    process.exit(1)
  })
}
