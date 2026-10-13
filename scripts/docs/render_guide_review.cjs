const fs = require('node:fs');
const path = require('node:path');
const sharp = require('C:/Users/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const qa = path.resolve(__dirname, '../../outputs/methodologist-production-guide-20261013/qa');
(async () => {
  const names = fs.readdirSync(qa).filter(n => n.endsWith('.png')).sort();
  if (names.length !== 24) throw Error('Expected 24 annotated captures');
  for (let i = 0; i < names.length; i += 4) {
    const tiles = await Promise.all(names.slice(i, i + 4).map(async (name, j) => {
      const image = await sharp(path.join(qa, name)).resize(850, 630, { fit: 'contain', background: 'white' }).toBuffer();
      return { input: image, left: (j % 2) * 850, top: Math.floor(j / 2) * 680 + 40 };
    }));
    const labels = names.slice(i, i + 4).map((name, j) => `<text x="${(j % 2) * 850 + 12}" y="${Math.floor(j / 2) * 680 + 27}" font-family="Arial" font-size="22">${name}</text>`).join('');
    await sharp({ create: { width: 1700, height: 1360, channels: 3, background: '#e9eff4' } }).composite([...tiles, { input: Buffer.from(`<svg width="1700" height="1360">${labels}</svg>`), left: 0, top: 0 }]).jpeg({ quality: 90 }).toFile(path.join(qa, `sheet-${i / 4 + 1}.jpg`));
  }
  console.log(JSON.stringify({ sheets: 6, annotated_screens: 24, result: 'RENDERED_PENDING_VISUAL_REVIEW' }));
})();
