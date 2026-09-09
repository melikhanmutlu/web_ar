// Targeted, repeatable guard for model-viewer 4.2.0's AR-only scene update.
// Its normal scale/orientation update calls onUpdateScene without an active
// AR scene. Creating the XR menu then dereferences presentedScene=null.
// Leave active AR sessions unchanged. Re-evaluate when upgrading the vendor.
const fs = require('fs');
const path = require('path');
const file = path.join(__dirname, '..', 'static', 'js', 'model-viewer.min.js');
const source = fs.readFileSync(file, 'utf8');
const needle = 'this.onUpdateScene=()=>{';
const replacement = needle + 'if(!this.isPresenting||!this.presentedScene)return;';
if (source.includes(replacement)) {
  console.log('AR scene guard already present');
} else {
  if (source.split(needle).length !== 2) throw new Error('Unexpected vendor layout; review the AR renderer before patching');
  fs.writeFileSync(file, source.replace(needle, replacement));
  console.log('Patched inactive AR scene updates');
}
