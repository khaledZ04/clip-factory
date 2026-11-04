// One-time: sign in to Content Rewards so the submit bot can work.
// Opens a Chrome window -> you sign in -> once the campaign page shows "Submit clip",
// the sign-in is saved straight into the GitHub secret CR_SESSION and the window closes.
// Run again whenever the bot says the sign-in expired.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const CAMPAIGN = 'https://contentrewards.com/c/campaigns/e73e9e9c-fba4-4c8b-9c0e-6fb1e607c2a5';
const GH = 'C:\\Program Files\\GitHub CLI\\gh.exe';

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: false, ignoreDefaultArgs: ['--enable-automation'] });
  const ctx = await browser.newContext({ viewport: null });
  const page = await ctx.newPage();
  await page.goto(CAMPAIGN);
  console.log('Sign in to Content Rewards in the Chrome window that opened. Waiting up to 10 minutes...');
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    await page.waitForTimeout(4000);
    try {
      if (!page.url().includes('/c/campaigns/')) continue;
      const signedIn = await page.evaluate(() => !/log ?in|sign ?in/i.test(document.body.innerText.slice(0, 3000)) || !!document.querySelector('img[alt*="avatar" i]'));
      const hasSubmit = await page.getByRole('button', { name: 'Submit clip' }).count();
      if (signedIn && hasSubmit) break;
    } catch (e) { /* page still loading */ }
  }
  await page.waitForTimeout(3000);
  const state = await ctx.storageState();
  state.origins = state.origins.filter(o => o.origin.includes('contentrewards'));
  const file = path.join(os.tmpdir(), 'cr-session.json');
  fs.writeFileSync(file, JSON.stringify(state));
  execFileSync(GH, ['secret', 'set', 'CR_SESSION', '-R', 'khaledZ04/clip-factory'], { input: fs.readFileSync(file) });
  fs.unlinkSync(file);
  await browser.close();
  console.log('Saved. The submit bot is signed in now.');
})().catch(e => { console.error(e.message); process.exit(1); });
