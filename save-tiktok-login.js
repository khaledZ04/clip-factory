// One-time: sign in to TikTok (jancostudios) so the posting bot can post.
// Opens a Chrome window -> you sign in -> once TikTok Studio opens, the sign-in is saved into the
// GitHub secret TT_SESSION (and a local copy for testing on this PC), then the window closes.
// Run again whenever the bot says the TikTok sign-in expired.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path');

const GH = 'C:\\Program Files\\GitHub CLI\\gh.exe';
const LOCAL = path.join(__dirname, 'tt-session.json');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: false, ignoreDefaultArgs: ['--enable-automation'], args: ['--disable-blink-features=AutomationControlled'] });
  const ctx = await browser.newContext({ viewport: null });
  const page = await ctx.newPage();
  await page.goto('https://www.tiktok.com/login?redirect_url=' + encodeURIComponent('https://www.tiktok.com/tiktokstudio/upload'));
  console.log('Sign in to TikTok as jancostudios in the Chrome window. Waiting up to 10 minutes...');
  const deadline = Date.now() + 10 * 60 * 1000;
  let ok = false;
  while (Date.now() < deadline && !ok) {
    await page.waitForTimeout(4000);
    const cookies = await ctx.cookies('https://www.tiktok.com');
    ok = cookies.some((c) => c.name === 'sessionid' && c.value) && /tiktokstudio/.test(page.url());
    if (!ok && cookies.some((c) => c.name === 'sessionid' && c.value) && !/tiktokstudio/.test(page.url()) && !/login/.test(page.url())) {
      await page.goto('https://www.tiktok.com/tiktokstudio/upload').catch(() => {});
    }
  }
  if (!ok) { console.log('Timed out - run it again.'); await browser.close(); process.exit(1); }
  await page.waitForTimeout(5000);
  const state = await ctx.storageState();
  // GitHub secrets max 48 KB: keep only TikTok cookies (the sign-in), drop the page cache.
  state.cookies = state.cookies.filter((c) => /tiktok.com$/.test(c.domain));
  state.origins = [];
  fs.writeFileSync(LOCAL, JSON.stringify(state));
  execFileSync(GH, ['secret', 'set', 'TT_SESSION', '-R', 'khaledZ04/clip-factory'], { input: fs.readFileSync(LOCAL) });
  await browser.close();
  console.log('Saved. The TikTok bot is signed in now.');
})().catch((e) => { console.error(e.message); process.exit(1); });
