const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.join(process.argv[2], 'playwright'));
const root = path.resolve(__dirname, '..');
const profile = JSON.parse(fs.readFileSync(path.join(root, 'deployment/private/windows.json'), 'utf8').replace(/^\uFEFF/, ''));
const registry = JSON.parse(fs.readFileSync(profile.model_registry_path, 'utf8'));

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const reports = [];
  try {
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      const context = await browser.newContext({ viewport: {width, height}, httpCredentials: {username: 'operator', password: profile.local_admin_token} });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('http://127.0.0.1:8765/', {waitUntil: 'networkidle'});
      await page.getByRole('heading', {name:'Model releases', exact:true}).waitFor();
      const input = page.getByLabel('Candling JPEG', {exact:true});
      await input.waitFor();
      await page.getByLabel('Comparison model').selectOption('age16-18');
      const entry = registry.models.find(model => model.id === 'age16-18');
      const fixture = path.join(path.dirname(profile.model_registry_path), entry.known_answer.path);
      await input.setInputFiles(fixture);
      await page.getByRole('button', {name:'Analyze image', exact:true}).click();
      await page.getByRole('heading', {name:'Review / recapture', exact:true}).waitFor();
      const overflow = await page.evaluate(() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth}));
      if (overflow.scrollWidth > overflow.innerWidth) throw new Error(`${name} horizontal overflow`);
      if (errors.length) throw new Error(`${name} browser errors: ${errors.join('; ')}`);
      await page.screenshot({path:path.join(root, `artifacts/production-ui-${name}.png`), fullPage:true});
      reports.push({viewport:name,width,height,upload_and_prediction:true,review_outcome_visible:true,no_horizontal_overflow:true,browser_errors:errors});
      await context.close();
    }
    fs.writeFileSync(path.join(root, 'artifacts/production-ui-verification.json'), JSON.stringify({passed:true,reports},null,2)+'\n');
    console.log(JSON.stringify({passed:true,reports},null,2));
  } finally { await browser.close(); }
})().catch(error => {console.error(error.message);process.exitCode=1;});
