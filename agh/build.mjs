// Build only the audited core dependency closure; upstream stays outside the repository.
import { build } from 'esbuild';
import { readFile, realpath, mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
const upstream = await realpath(process.env.PAIR_AKI_AGH_UPSTREAM || '');
const manifestText = await readFile(join(upstream, 'source-manifest.json'), 'utf8');
if (createHash('sha256').update(manifestText).digest('hex') !== '7578115f2ba304ce2a85caca06bfd870e76031819a7f2d577842cb21496362f2') throw Error('source_manifest_not_audited');
const manifest = JSON.parse(manifestText);
if (manifest.commit !== '4bc36bc4c4441206388a53bece17379c1d7be14d') throw Error('source_pin_mismatch');
for (const [path, expected] of Object.entries(manifest.files)) {
  const actual = createHash('sha256').update(await readFile(join(upstream, path))).digest('hex');
  if (actual !== expected) throw Error('source_sha_mismatch:' + path);
}
const packages = ['core', 'protocol', 'protocol-validation', 'extension-api', 'resource-control-contracts'];
const aliases = Object.fromEntries(packages.map(name => ['@agnes/' + name, join(upstream, 'packages', name, 'src/index.ts')]));
aliases['@agnes/protocol/gen'] = join(upstream, 'packages/protocol/gen/ts');
const output = resolve(process.env.PAIR_AKI_AGH_BUILD || 'dist');
await mkdir(output, {recursive: true});
const result = await build({entryPoints: ['runner.ts'], outdir: output, outExtension: {'.js': '.mjs'},
  bundle: true, platform: 'node', target: 'node24', format: 'esm', alias: aliases,
  packages: 'bundle', metafile: true, external: ['@sinclair/typebox', '@sinclair/typebox/*']});
await writeFile(join(output, 'build-inputs.json'), JSON.stringify(result.metafile.inputs, null, 2));
console.log(JSON.stringify({status: 'built', upstream_commit: manifest.commit, modules: Object.keys(result.metafile.inputs).length}));
