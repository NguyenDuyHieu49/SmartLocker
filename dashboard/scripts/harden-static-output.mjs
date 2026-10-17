import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { dirname, extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const publicDir = join(projectRoot, '.output', 'public')

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) files.push(...await walk(path))
    else files.push(path)
  }

  return files
}

const files = await walk(publicDir)
const htmlFiles = files.filter(path => extname(path) === '.html')
const jsFiles = files.filter(path => extname(path) === '.js')

if (htmlFiles.length === 0) throw new Error('No generated HTML files found')

const importMapPattern = /<script type="importmap">({.*?})<\/script>/
const runtimeConfigPattern = /<script>(window\.__NUXT__=\{\};window\.__NUXT__\.config=.*?)<\/script>/
let entryPath
let runtimeConfig

for (const htmlFile of htmlFiles) {
  let html = await readFile(htmlFile, 'utf8')
  const importMapMatch = html.match(importMapPattern)
  const configMatch = html.match(runtimeConfigPattern)

  if (!importMapMatch || !configMatch) {
    throw new Error(`Expected Nuxt bootstrap scripts in ${relative(projectRoot, htmlFile)}`)
  }

  const importMap = JSON.parse(importMapMatch[1])
  const currentEntryPath = importMap.imports?.['#entry']
  if (!currentEntryPath) throw new Error(`Missing #entry import in ${relative(projectRoot, htmlFile)}`)

  entryPath ??= currentEntryPath
  runtimeConfig ??= configMatch[1]

  if (currentEntryPath !== entryPath || configMatch[1] !== runtimeConfig) {
    throw new Error('Generated pages do not share one Nuxt bootstrap configuration')
  }

  html = html
    .replace(importMapPattern, '')
    .replace(runtimeConfigPattern, '')
    .replace('<head>', '<head><script src="/_nuxt/runtime-config.js"></script>')

  await writeFile(htmlFile, html)
}

const entryFileName = entryPath.split('/').at(-1)
if (!entryFileName) throw new Error('Invalid Nuxt entry path')

for (const jsFile of jsFiles) {
  const source = await readFile(jsFile, 'utf8')
  const rewritten = source.replaceAll('"#entry"', `"./${entryFileName}"`)
  if (rewritten !== source) await writeFile(jsFile, rewritten)
}

const runtimeConfigPath = join(publicDir, '_nuxt', 'runtime-config.js')
await mkdir(dirname(runtimeConfigPath), { recursive: true })
await writeFile(runtimeConfigPath, `${runtimeConfig}\n`)

const remainingBareImports = []
for (const jsFile of jsFiles) {
  const source = await readFile(jsFile, 'utf8')
  if (source.includes('"#entry"')) remainingBareImports.push(relative(projectRoot, jsFile))
}

if (remainingBareImports.length > 0) {
  throw new Error(`Unresolved #entry imports: ${remainingBareImports.join(', ')}`)
}

console.log(`Hardened ${htmlFiles.length} static pages for CSP script-src 'self'`)
