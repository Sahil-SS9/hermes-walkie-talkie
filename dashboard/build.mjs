import * as esbuild from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync } from 'fs';

const isProd = !process.argv.includes('--dev');

// Bundle JS
const jsResult = await esbuild.build({
  entryPoints: ['src/index.ts'],
  bundle: true,
  minify: isProd,
  sourcemap: !isProd,
  format: 'esm',
  target: 'es2022',
  outfile: 'dist/index.js',
  metafile: true,
  write: false,
});

mkdirSync('dist', { recursive: true });
writeFileSync('dist/index.js', jsResult.outputFiles[0].contents);

// Bundle CSS
const cssResult = await esbuild.build({
  entryPoints: ['src/style.css'],
  bundle: true,
  minify: isProd,
  loader: { '.css': 'css' },
  outfile: 'dist/style.css',
  write: false,
});

writeFileSync('dist/style.css', cssResult.outputFiles[0].contents);

// Write metadata
if (isProd) {
  writeFileSync('dist/build-meta.json', JSON.stringify({
    inputs: jsResult.metafile.inputs,
    bytes: { js: jsResult.outputFiles[0].contents.length, css: cssResult.outputFiles[0].contents.length },
  }, null, 2));
}

console.log(`Built: dist/index.js (${jsResult.outputFiles[0].contents.length} bytes), dist/style.css (${cssResult.outputFiles[0].contents.length} bytes)`);
