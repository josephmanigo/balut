// Local UI/device check. API responses are isolated; no frames reach cloud storage.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(path.join(process.argv[2], 'playwright'));
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'output', 'webcam-verification');
const real = process.argv.includes('--real-camera');
fs.mkdirSync(out, { recursive: true });
const blank = { cloudCapture: true, cameraUrl: '', enabled: false, calibrated: false, connected: false,
  state: 'offline', preview: null, result: null, error: null };

(async () => {
  const server = http.createServer((req, res) => {
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const file = path.resolve(root, 'apps/web/dist', name === '/' ? 'index.html' : '.' + name);
    if (!file.startsWith(path.join(root, 'apps/web/dist') + path.sep) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' })[path.extname(file)] || 'application/octet-stream');
    res.setHeader('Permissions-Policy', 'camera=(self), microphone=(), geolocation=(), serial=(self)');
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ channel: 'msedge', headless: true,
    args: ['--use-fake-ui-for-media-stream', ...(!real ? ['--use-fake-device-for-media-stream'] : [])] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['camera'] });
    const page = await context.newPage();
    const errors = [], uploads = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), url = new URL(request.url());
      let value = {};
      if (url.pathname.endsWith('/auth/session')) value = { authenticated: true, sharedStorage: true };
      else if (url.pathname.endsWith('/box/status')) value = blank;
      else if (url.pathname.endsWith('/model-predictions')) value = { items: [] };
      else if (url.pathname.endsWith('/box/frame')) {
        uploads.push({ key: request.headers()['idempotency-key'], bytes: request.postDataBuffer().length });
        if (uploads.length === 1) await new Promise(resolve => setTimeout(resolve, 2000));
        value = { accepted: true };
      }
      await route.fulfill({ json: value });
    });
    const origin = `http://127.0.0.1:${server.address().port}`;
    await page.goto(origin);
    await page.getByText('Box setup', { exact: true }).click();
    await page.getByRole('button', { name: 'Connect EMEET / webcam' }).click();
    await page.waitForFunction(() => document.querySelector('video')?.videoWidth > 0, { timeout: 20000 });
    const measure = await page.locator('video').evaluate(video => new Promise(resolve => {
      const start = performance.now();
      let count = 0;
      const frame = () => { count++; video.requestVideoFrameCallback(frame); };
      video.requestVideoFrameCallback(frame);
      setTimeout(() => resolve({ settings: video.srcObject.getVideoTracks()[0].getSettings(),
        label: video.srcObject.getVideoTracks()[0].label, measuredFps: count / ((performance.now() - start) / 1000),
        width: video.videoWidth, height: video.videoHeight, currentTime: video.currentTime }), 8000);
    }));
    assert.ok(uploads.length >= 3, 'fresh stream frames must upload');
    assert.equal(new Set(uploads.map(value => value.key)).size, uploads.length);
    assert.ok(uploads.every(value => value.bytes <= 512 * 1024 && value.key.startsWith('webcam-')));
    assert.equal(measure.width, 1920); assert.equal(measure.height, 1080);
    assert.equal(await page.getByText('Live camera connected.', { exact: true }).count(), 1);
    await page.screenshot({ path: path.join(out, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(out, 'mobile.png'), fullPage: true });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('video')?.videoWidth > 0);
    await page.getByText('Box setup', { exact: true }).click();
    await page.getByRole('button', { name: 'Disconnect webcam' }).click();
    assert.equal(await page.locator('video').count(), 0);
    assert.deepEqual(errors, []);
    const report = { passed: true, realCamera: real, api: 'isolated mock; no cloud predictions', ...measure,
      uploadedFrames: uploads.length, maxUploadBytes: Math.max(...uploads.map(value => value.bytes)), errors };
    fs.writeFileSync(path.join(out, real ? 'real-camera.json' : 'simulated-camera.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
