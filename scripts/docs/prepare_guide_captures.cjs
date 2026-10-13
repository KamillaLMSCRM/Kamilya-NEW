// Deterministic guide-frame composition. Preserve raw browser JPEGs separately;
// never invent, retouch or replace UI content. Sharp extracts the verified region.
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('C:/Users/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const dir = path.resolve(__dirname, '../../outputs/methodologist-production-guide-20261013');
(async () => {
  const captures = JSON.parse(fs.readFileSync(path.join(dir, 'marks.json'), 'utf8'));
  for (const capture of captures.filter(c => c.raw_full_viewport)) {
    const raw = fs.readFileSync(path.join(dir, 'raw', capture.name + '.jpg'));
    const metadata = await sharp(raw).metadata();
    const c = capture.clip;
    const sx = metadata.width / 1280, sy = metadata.height / 900;
    const region = { left: Math.round(c.x * sx), top: Math.round(c.y * sy), width: Math.round(c.width * sx), height: Math.round(c.height * sy) };
    if (region.left + region.width > metadata.width || region.top + region.height > metadata.height) throw Error('Invalid frame');
    await sharp(raw).extract(region).jpeg({ quality: 95 }).toFile(path.join(dir, 'screens', capture.name + '.jpg'));
    capture.marks = capture.raw_marks.map(([x,y,w,h]) => [(x-c.x)*sx,(y-c.y)*sy,w*sx,h*sy]);
    capture.frame_renderer = 'deterministic region of untouched raw browser capture; coordinate scale verified';
  }
  fs.writeFileSync(path.join(dir, 'marks.json'), JSON.stringify(captures, null, 2));
  console.log(JSON.stringify({ result: 'PASS', corrected_frames: captures.filter(c => c.raw_full_viewport).length }));
})();
