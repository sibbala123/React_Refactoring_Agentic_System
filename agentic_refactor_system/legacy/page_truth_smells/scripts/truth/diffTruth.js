import fs from 'node:fs/promises'
import path from 'node:path'
import { getCliArg } from './helpers.js'

const STYLE_FIELDS = ['color', 'backgroundColor', 'fontSize', 'fontWeight', 'borderRadius', 'display', 'visibility']
const BOX_FIELDS = ['x', 'y', 'w', 'h']

function stableTruthFiles(entries) {
  return entries
    .filter((name) => /^truth__.+\.json$/i.test(name))
    .sort((a, b) => a.localeCompare(b))
}

async function readTruthFolder(folder) {
  const names = await fs.readdir(folder)
  const files = stableTruthFiles(names)
  const map = new Map()
  for (const file of files) {
    const raw = await fs.readFile(path.join(folder, file), 'utf8')
    map.set(file, JSON.parse(raw))
  }
  return map
}

function diffPrimitive(baseVal, candVal, label, diffs) {
  if (baseVal !== candVal) {
    diffs.push(`${label}: "${baseVal}" -> "${candVal}"`)
  }
}

function routeStateLabel(doc, fallback) {
  if (!doc || !doc.route || !doc.state) return fallback
  return `${doc.route}#${doc.state}`
}

function elementsByKey(elements) {
  const map = new Map()
  for (const el of elements) {
    if (!el || typeof el.key !== 'string') continue
    map.set(el.key, el)
  }
  return map
}

function keysByOrder(elements) {
  return [...elements]
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map((el) => el.key)
}

function compareElementsByKey(label, baseElements, candElements, diffs) {
  const baseMap = elementsByKey(baseElements)
  const candMap = elementsByKey(candElements)

  for (const key of baseMap.keys()) {
    if (!candMap.has(key)) {
      diffs.push(`[${label}] missing in candidate: key=${key}`)
    }
  }
  for (const key of candMap.keys()) {
    if (!baseMap.has(key)) {
      diffs.push(`[${label}] extra in candidate: key=${key}`)
    }
  }

  const shared = [...baseMap.keys()].filter((key) => candMap.has(key)).sort((a, b) => a.localeCompare(b))
  for (const key of shared) {
    const b = baseMap.get(key)
    const c = candMap.get(key)
    const prefix = `[${label}] key=${key}`

    diffPrimitive(b.role, c.role, `${prefix}.role`, diffs)
    diffPrimitive(b.name, c.name, `${prefix}.name`, diffs)
    diffPrimitive(b.order, c.order, `${prefix}.order`, diffs)

    for (const boxField of BOX_FIELDS) {
      diffPrimitive(b.box?.[boxField], c.box?.[boxField], `${prefix}.box.${boxField}`, diffs)
    }
    for (const styleField of STYLE_FIELDS) {
      diffPrimitive(b.style?.[styleField], c.style?.[styleField], `${prefix}.style.${styleField}`, diffs)
    }
  }

  const baseOrder = keysByOrder(baseElements)
  const candOrder = keysByOrder(candElements)
  if (baseOrder.length !== candOrder.length) {
    diffs.push(`[${label}] order regression: key count ${baseOrder.length} -> ${candOrder.length}`)
  } else {
    for (let i = 0; i < baseOrder.length; i += 1) {
      if (baseOrder[i] !== candOrder[i]) {
        diffs.push(
          `[${label}] order regression at index ${i}: baseline=${baseOrder[i]} candidate=${candOrder[i]}`,
        )
      }
    }
  }
}

async function run() {
  const cwd = process.cwd()
  const baseArg = getCliArg('--base') || 'truth_baseline'
  const candArg = getCliArg('--cand') || 'truth_candidate'
  const baselineDir = path.isAbsolute(baseArg) ? baseArg : path.join(cwd, baseArg)
  const candidateDir = path.isAbsolute(candArg) ? candArg : path.join(cwd, candArg)

  const [baseMap, candMap] = await Promise.all([readTruthFolder(baselineDir), readTruthFolder(candidateDir)])

  const diffs = []
  const baseFiles = [...baseMap.keys()]
  const candFiles = [...candMap.keys()]

  for (const file of baseFiles) {
    if (!candMap.has(file)) diffs.push(`Missing in candidate folder: ${file}`)
  }
  for (const file of candFiles) {
    if (!baseMap.has(file)) diffs.push(`Missing in baseline folder: ${file}`)
  }

  const shared = baseFiles.filter((file) => candMap.has(file)).sort((a, b) => a.localeCompare(b))
  for (const file of shared) {
    const baseDoc = baseMap.get(file)
    const candDoc = candMap.get(file)
    const label = routeStateLabel(candDoc, file)

    diffPrimitive(baseDoc.version, candDoc.version, `[${label}].version`, diffs)
    diffPrimitive(baseDoc.route, candDoc.route, `[${label}].route`, diffs)
    diffPrimitive(baseDoc.state, candDoc.state, `[${label}].state`, diffs)
    diffPrimitive(baseDoc.env?.browser, candDoc.env?.browser, `[${label}].env.browser`, diffs)
    diffPrimitive(baseDoc.env?.viewport?.width, candDoc.env?.viewport?.width, `[${label}].env.viewport.width`, diffs)
    diffPrimitive(baseDoc.env?.viewport?.height, candDoc.env?.viewport?.height, `[${label}].env.viewport.height`, diffs)
    diffPrimitive(
      baseDoc.env?.deviceScaleFactor,
      candDoc.env?.deviceScaleFactor,
      `[${label}].env.deviceScaleFactor`,
      diffs,
    )

    const baseElements = Array.isArray(baseDoc.elements) ? baseDoc.elements : []
    const candElements = Array.isArray(candDoc.elements) ? candDoc.elements : []
    compareElementsByKey(label, baseElements, candElements, diffs)
  }

  if (diffs.length) {
    console.error('Truth diff failed:')
    for (const line of diffs) {
      console.error(`- ${line}`)
    }
    process.exit(1)
  }

  console.log('Truth diff passed: no differences found.')
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
