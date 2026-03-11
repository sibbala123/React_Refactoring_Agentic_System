import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { chromium } from 'playwright'
import { FIXED_ENV, TRUTH_VERSION, ensureDir, getCliArg, outputFileName, readRoutesConfig, resolveOutputDir, writeJson } from './helpers.js'

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
    if (step[type]) {
      return { type, ...step[type] }
    }
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

async function collectElements(page) {
  return page.evaluate(() => {
    const INCLUDED_ROLES = new Set([
      'button',
      'link',
      'textbox',
      'checkbox',
      'radio',
      'combobox',
      'listbox',
      'switch',
      'heading',
      'dialog',
    ])

    function rounded(n) {
      return Number(n.toFixed(2))
    }

    function textContentTrimmed(el) {
      return (el.textContent || '').replace(/\s+/g, ' ').trim()
    }

    function inferRole(el) {
      const explicit = el.getAttribute('role')
      if (explicit) return explicit

      const tag = el.tagName.toLowerCase()
      if (/^h[1-6]$/.test(tag)) return 'heading'
      if (tag === 'button') return 'button'
      if (tag === 'a' && el.getAttribute('href')) return 'link'
      if (tag === 'dialog') return 'dialog'
      if (tag === 'select') return 'combobox'
      if (tag === 'textarea') return 'textbox'
      if (tag === 'input') {
        const type = (el.getAttribute('type') || 'text').toLowerCase()
        if (type === 'checkbox') return 'checkbox'
        if (type === 'radio') return 'radio'
        return 'textbox'
      }
      return tag
    }

    function readLabelledBy(el) {
      const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
      if (!ids.length) return ''
      const text = ids
        .map((id) => {
          const ref = document.getElementById(id)
          return ref ? textContentTrimmed(ref) : ''
        })
        .filter(Boolean)
        .join(' ')
      return text.trim()
    }

    function inferName(el, role) {
      const ariaLabel = (el.getAttribute('aria-label') || '').trim()
      if (ariaLabel) return ariaLabel

      const labelledBy = readLabelledBy(el)
      if (labelledBy) return labelledBy

      if (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea' || role === 'textbox') {
        const byLabel = (el.labels && el.labels[0] && textContentTrimmed(el.labels[0])) || ''
        if (byLabel) return byLabel
        const placeholder = (el.getAttribute('placeholder') || '').trim()
        if (placeholder) return placeholder
      }

      if (role === 'button' || role === 'link' || role === 'heading') {
        return textContentTrimmed(el)
      }

      return ''
    }

    function isVisible(el) {
      const style = window.getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden') return false
      const rect = el.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return false
      if (rect.bottom < 0 || rect.right < 0) return false
      if (rect.top > window.innerHeight || rect.left > window.innerWidth) return false
      return true
    }

    function styleSignature(el) {
      const style = window.getComputedStyle(el)
      return {
        color: style.color,
        backgroundColor: style.backgroundColor,
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        borderRadius: style.borderRadius,
        display: style.display,
        visibility: style.visibility,
      }
    }

    function elementRecord(el, forcedRole = '') {
      const role = forcedRole || inferRole(el)
      const name = inferName(el, role)
      const rect = el.getBoundingClientRect()
      return {
        el,
        testId: (el.getAttribute('data-testid') || '').trim(),
        role,
        name,
        box: {
          x: rounded(rect.x),
          y: rounded(rect.y),
          w: rounded(rect.width),
          h: rounded(rect.height),
        },
        style: styleSignature(el),
      }
    }

    const picked = []
    const seen = new Set()

    const main = document.querySelector('main') || document.querySelector('#root > *')
    if (main && isVisible(main)) {
      picked.push(elementRecord(main, 'main'))
      seen.add(main)
    }

    const all = Array.from(document.querySelectorAll('*'))
    for (const el of all) {
      if (seen.has(el)) continue
      if (!isVisible(el)) continue

      const role = inferRole(el)
      const tag = el.tagName.toLowerCase()
      const isHeadingTag = /^h[1-6]$/.test(tag)
      if (!INCLUDED_ROLES.has(role) && !isHeadingTag) continue
      picked.push(elementRecord(el))
    }

    picked.sort((a, b) => {
      if (a.box.y !== b.box.y) return a.box.y - b.box.y
      if (a.box.x !== b.box.x) return a.box.x - b.box.x
      if (a.role !== b.role) return a.role.localeCompare(b.role)
      return a.name.localeCompare(b.name)
    })

    return picked.map((entry, index) => {
      const geometryKey = `${entry.role}|${entry.name}|x=${entry.box.x}|y=${entry.box.y}|w=${entry.box.w}|h=${entry.box.h}`

      return {
        key: entry.testId ? `testid:${entry.testId}` : geometryKey,
        role: entry.role,
        name: entry.name,
        order: index,
        box: entry.box,
        style: entry.style,
      }
    })
  })
}

export async function runTruthGeneration(outDirArg = 'truth') {
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

        const steps = Array.isArray(state.steps) ? state.steps : []
        for (const step of steps) {
          await runStep(page, step)
        }

        const elements = await collectElements(page)
        const fileName = outputFileName(route.path, state.name)
        const payload = {
          version: TRUTH_VERSION,
          route: route.path,
          state: state.name,
          env: FIXED_ENV,
          elements,
        }

        const outputPath = path.join(outputDir, fileName)
        await writeJson(outputPath, payload)
        const generatedAt = new Date().toISOString()
        generated.push({ file: fileName, route: route.path, state: state.name, generatedAt })
        await page.close()
        console.log(`Generated ${fileName}`)
      }
    }
  } finally {
    await context.close()
    await browser.close()
  }

  await writeJson(path.join(outputDir, 'index.json'), {
    generatedAt: new Date().toISOString(),
    files: generated,
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const outArg = getCliArg('--out')
  runTruthGeneration(outArg || 'truth').catch((err) => {
    console.error(err)
    process.exit(1)
  })
}
