const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

async function main() {
  const [source, output] = process.argv.slice(2);
  const engineDir = path.join(__dirname, 'engine');
  const bundle = path.join(engineDir, 'core.mjs');
  const srcExt = path.extname(source).slice(1).toLowerCase();
  const dstExt = path.extname(output).slice(1).toLowerCase();
  if (srcExt === 'doc' || dstExt === 'doc') {
    const { convertFile } = require(path.join(engineDir, 'legacy.cjs'));
    const result = await convertFile(source, output, { bundlePath: bundle, timeout: 180 });
    for (const warning of result.warns) console.error('[warn]', warning);
  } else {
    const { Pipeline } = await import(pathToFileURL(bundle).href);
    const bytes = new Uint8Array(await fs.readFile(source));
    const input = ['md', 'html'].includes(srcExt) ? new TextDecoder().decode(bytes) : bytes;
    const result = await Pipeline.open(input, ['md', 'html'].includes(srcExt) ? srcExt : undefined).to(dstExt);
    if (!result.ok) throw new Error(result.error);
    for (const warning of result.warns || []) console.error('[warn]', warning);
    await fs.writeFile(output, result.data);
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
