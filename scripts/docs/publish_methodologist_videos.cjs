// Import only the owner-approved, independently checked male Qwen media export.
// Usage: node scripts/docs/publish_methodologist_videos.cjs <rendered-directory>
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const source = path.resolve(process.argv[2] || '');
const guides = path.join(root, 'apps/web/public/guides');
const media = path.join(guides, 'methodologist-qwen-male');
const approved = {
  '01-sources': 'b73f3388076978d8040c9f5056f0ba9ced0007d56de939add43a5a22016296fc',
  '02-generation': '854b7ae0403a89c3264f61e6c54deb36820d5b5256efea2bf37747dc500f6f0f',
  '03-lessons': 'a6c7890306cef81d8aeaecb4f04230b38e5db2551b0d9d31c1904f73b30d6689',
  '04-tests': 'bf75b1d82b6843cfb5831ba172de545de88183b39de99fdae84d9f3eebeced29',
  '05-publication': 'b0250b564bf95b11a26885debae843264fe7f40a796940344c9a50037d1ff889',
  '06-staff': '060b9457639b4a7f4f5484b9b365afab1ca492320c66443f6f2f498c8ff6b0e1',
  '07-assignment': '1df0a52eaae88963ab7a796aa0b62967baaefa4cf6bb582f027bb1b78a080489',
  '08-results': '2e7fd97686b4d952b927fc3363e83b5e7a5cf48f3c9d5d180b8a008dce26d0ad',
};
const digest = data => crypto.createHash('sha256').update(data).digest('hex');
const qa = JSON.parse(fs.readFileSync(path.join(source, 'qa.json'), 'utf8'));
assert.equal(qa.videos.length, 8);
assert.equal(qa.videos.reduce((sum, v) => sum + v.segments, 0), 69);
const assets = [];
// Validate everything before changing the public directory.
for (const video of qa.videos) {
  assert.equal(video.sha256, approved[video.id]);
  for (const suffix of ['.mp4', '-poster.jpg', '.srt', '.vtt']) {
    const name = video.id + suffix;
    const bytes = fs.readFileSync(path.join(source, name));
    if (suffix === '.mp4') assert.equal(digest(bytes), approved[video.id]);
    assets.push({ name, bytes, sha256: digest(bytes) });
  }
}
let html = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
assert.equal((html.match(/<video /g) || []).length, 8);
assert.ok(html.includes('Мужской синтетический голос Qwen3-TTS.'));
html = html.replace('<title>', '<meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; media-src \'self\'; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; connect-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>');
html = html.replace('</h1>', '</h1><p><strong>Мужская озвучка Qwen · 8 процессов · 69 шагов · около 8 минут</strong></p><p><a href="/">Вернуться в кабинет</a> · <a href="methodologist-text.html">Текстовая инструкция со скриншотами</a></p>');
for (const asset of assets) {
  html = html.replaceAll(`src="${asset.name}"`, `src="methodologist-qwen-male/${asset.name}"`)
    .replaceAll(`poster="${asset.name}"`, `poster="methodologist-qwen-male/${asset.name}"`)
    .replaceAll(`href="${asset.name}"`, `href="methodologist-qwen-male/${asset.name}"`);
}
html = html.replace('Комплект работает локально: держите HTML, видео, постеры и субтитры в одной папке. Интернет и вход в кабинет для просмотра не нужны.', 'Для просмотра этой страницы нужен интернет. MP4 и субтитры можно скачать под каждым роликом и смотреть локально. Экраны сняты в учебном кабинете; реальные названия и данные вашей организации будут отличаться.');
html = html.replace('document.addEventListener("click",', 'document.addEventListener("play",function(e){if(e.target.tagName!=="VIDEO")return;document.querySelectorAll("video").forEach(function(v){if(v!==e.target)v.pause();});},true);document.addEventListener("click",');
fs.mkdirSync(media, { recursive: true });
const legacy = path.join(guides, 'methodologist-text.html');
if (!fs.existsSync(legacy)) {
  const current = fs.readFileSync(path.join(guides, 'methodologist.html'));
  assert.ok(current.includes(Buffer.from('pilot-progress')), 'Expected original text guide');
  fs.writeFileSync(legacy, current);
}
for (const asset of assets) fs.writeFileSync(path.join(media, asset.name), asset.bytes);
fs.writeFileSync(path.join(guides, 'methodologist.html'), html);
const manifest = {
  schema: 'kamilya-methodologist-video-guide-v1', language: 'ru', voice: 'Qwen3-TTS synthetic male',
  release_date: '2026-10-16', steps: 69,
  videos: qa.videos.map(v => ({ id: v.id, steps: v.segments, duration_seconds: v.video_seconds, sha256: v.sha256 })),
  assets: assets.map(({ name, bytes, sha256 }) => ({ name, bytes: bytes.length, sha256 })),
};
fs.writeFileSync(path.join(media, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(JSON.stringify({ result: 'PASS', videos: 8, steps: 69, public_assets: assets.length, html_bytes: Buffer.byteLength(html) }));
