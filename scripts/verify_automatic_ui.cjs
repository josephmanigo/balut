// Regression test for the built application, with an isolated local test server.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.join(process.argv[2], 'playwright'));
const root = path.resolve(__dirname, '..');
const profile = JSON.parse(fs.readFileSync(process.argv[3], 'utf8').replace(/^\uFEFF/, ''));
const registry = JSON.parse(fs.readFileSync(profile.model_registry_path, 'utf8'));
const prefix = process.argv[4] || 'automatic';
const reportPrefix = process.argv[5] || prefix;
const selective = prefix === 'selective';
const titles = {DAY_16:'Day 16', DAY_18:'Day 18', REJECT:'Reject — suspected'};

(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const reports = [];
  try {
    for (const [name, width, height] of [['desktop',1440,1000],['mobile',390,844]]) {
      const context = await browser.newContext({viewport:{width,height}, httpCredentials:{username:'operator',password:profile.local_admin_token}});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`http://127.0.0.1:${profile.port}/`, {waitUntil:'networkidle'});
      await page.getByRole('heading', {name:'Analyze egg',exact:true}).waitFor();
      if (await page.getByRole('combobox').count()) throw new Error('Operator still has to select a model');
      const input = page.getByLabel('Candling JPEG', {exact:true});
      const predictions = [];
      for (const example of registry.software_test_examples) {
        await input.setInputFiles(path.join(path.dirname(profile.model_registry_path),example.file.path));
        await page.getByRole('main').getByRole('button',{name:'Analyze egg',exact:true}).click();
        await page.getByRole('heading',{name:example.expected_prediction === null ? 'Another image needed' : titles[example.expected_prediction],exact:true}).waitFor();
        if (selective) {
          await page.getByText(example.expected_prediction === null ? 'Unclassified · new image requested automatically' : 'Automatic image prediction',{exact:true}).waitFor();
          if (await page.getByText('Image prediction · human confirmation required',{exact:true}).count()) throw new Error('Mandatory human review remains');
          if (example.expected_prediction === null && !await page.getByRole('main').getByRole('button',{name:'Analyze egg',exact:true}).isDisabled()) throw new Error('Unclear image can loop without replacement');
        } else {
          await page.getByText('Image prediction · human confirmation required',{exact:true}).waitFor();
        }
        predictions.push(example.expected_prediction);
      }
      const dimensions = await page.evaluate(() => ({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      if (dimensions.scroll > dimensions.width || errors.length) throw new Error('Rendered flow has overflow or browser errors');
      await page.screenshot({path:path.join(root,`artifacts/${reportPrefix}-ui-${name}.png`),fullPage:true});
      reports.push({viewport:name,width,height,no_model_dropdown:true,automatic_predictions:predictions,review_label_visible:!selective,automatic_recapture_verified:selective,no_horizontal_overflow:true,browser_errors:errors});
      await context.close();
    }
    const registrySha256 = require('node:crypto').createHash('sha256').update(fs.readFileSync(profile.model_registry_path)).digest('hex');
    const report = {passed:true,registry_sha256:registrySha256,reports};
    fs.writeFileSync(path.join(root,`artifacts/${reportPrefix}-ui-verification.json`), JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
