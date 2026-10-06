// Syntax-check every first-party script under static/js (skips vendored
// libraries and *.min.js bundles). Used by `npm run lint`.
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.join(__dirname, '..', 'static', 'js');
const SKIP_DIRS = new Set(['vendor', 'node_modules']);

function walk(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) walk(full, out);
    } else if (entry.name.endsWith('.js') && !entry.name.endsWith('.min.js')) {
      out.push(full);
    }
  }
  return out;
}

const files = walk(ROOT, []).sort();
let failed = 0;
for (const file of files) {
  const r = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
  if (r.status !== 0) {
    failed++;
    process.stderr.write(r.stderr);
  }
}
console.log(`Checked ${files.length} static JS files, ${failed} failed`);
process.exit(failed ? 1 : 0);
