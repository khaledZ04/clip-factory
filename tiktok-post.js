// Posts a clip on TikTok like a person would, in TikTok Studio on the web:
// open the upload page -> pick the file -> type the caption -> Post -> find the new video's link.
// Uses the sign-in saved by save-tiktok-login.js (GitHub secret TT_SESSION). Never sees a password.
//
// Usage: node tiktok-post.js <video.mp4> <caption-file.txt> <handle>
// env: TT_SESSION (saved sign-in JSON) or TT_SESSION_FILE, HEADED=1 to watch, DRY=1 to stop before Post.
// Prints "tiktok_url: <link>" on success. Exit codes: 2 = sign-in expired, 3 = TikTok asked for a puzzle.
const { chromium } = require('playwright');
const fs = require('fs');

const [video, captionFile, handle] = process.argv.slice(2);
const caption = fs.readFileSync(captionFile, 'utf8').trim();
const SHOTS = process.env.SHOTS || 'work';
fs.mkdirSync(SHOTS, { recursive: true });
const state = JSON.parse(process.env.TT_SESSION || fs.readFileSync(process.env.TT_SESSION_FILE, 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fail(page, code, msg) {
  try { await page.screenshot({ path: `${SHOTS}/tiktok-${code}.png` }); } catch (e) {}
  console.log('tiktok: ' + msg);
  process.exit(code);
}

async function checkBlocked(page) {
  if (/\/login/.test(page.url())) await fail(page, 2, 'LOGIN_EXPIRED - run save-tiktok-login.js again');
  const puzzle = await page.locator('#captcha_container, #captcha-verify-container, [class*="captcha" i]').count();
  if (puzzle) await fail(page, 3, 'CAPTCHA - TikTok asked to verify; post this one by hand');
}

async function videoIds(page) {
  await page.goto(`https://www.tiktok.com/@${handle}`, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await sleep(6000);
  await checkBlocked(page);
  return page.$$eval('a[href*="/video/"]', (as) => [...new Set(as.map((a) => (a.href.match(/\/video\/(\d+)/) || [])[1]).filter(Boolean))]);
}

(async () => {
  const browser = await chromium.launch({
    channel: 'chrome', headless: !process.env.HEADED,
    ignoreDefaultArgs: ['--enable-automation'], args: ['--disable-blink-features=AutomationControlled'],
  });
  const ctx = await browser.newContext({ storageState: state, viewport: { width: 1366, height: 900 }, locale: 'en-US' });
  const page = await ctx.newPage();

  const before = await videoIds(page).catch(() => []);

  await page.goto('https://www.tiktok.com/tiktokstudio/upload?from=webapp', { waitUntil: 'domcontentloaded', timeout: 90000 });
  await sleep(5000);
  await checkBlocked(page);
  const input = page.locator('input[type="file"]').first();
  await input.waitFor({ state: 'attached', timeout: 60000 });
  await input.setInputFiles(video);
  console.log('tiktok: file picked, uploading...');

  // Caption box (prefilled with the file name) appears once the upload starts.
  const box = page.locator('div[contenteditable="true"]').first();
  await box.waitFor({ timeout: 120000 });
  await sleep(3000);
  await box.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Backspace');
  for (const [i, line] of caption.split('\n').entries()) {
    if (i) await page.keyboard.press('Shift+Enter');
    for (const word of line.split(' ')) {
      await page.keyboard.insertText(word + ' ');
      await sleep(150);
      if (/^[@#]/.test(word)) await page.keyboard.press('Escape'); // close the mention/hashtag suggestion list
    }
  }
  await page.mouse.click(5, 300); // click away so the box keeps the text

  // Wait until the video finished uploading and the Post button is usable.
  const post = page.locator('button[data-e2e="post_video_button"], button:has-text("Post")').last();
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    await checkBlocked(page);
    const ready = await post.isEnabled().catch(() => false);
    const uploading = await page.getByText(/uploading|%/i).count().catch(() => 0);
    if (ready && !uploading) break;
    await sleep(3000);
  }
  await page.screenshot({ path: `${SHOTS}/tiktok-before.png` });
  if (process.env.DRY === '1') { console.log('tiktok: DRY - everything filled, not posting'); await browser.close(); return; }

  await post.click();
  // Some accounts get a "post now?" or content-check question first.
  for (let i = 0; i < 6; i++) {
    await sleep(3000);
    const again = page.locator('div[role="dialog"] button:has-text("Post"), button:has-text("Post now")').first();
    if (await again.count()) await again.click().catch(() => {});
    if (/tiktokstudio\/content|manage/i.test(page.url())) break;
  }
  await sleep(8000);
  await page.screenshot({ path: `${SHOTS}/tiktok-after.png` });
  await checkBlocked(page);

  // Find the new video on the profile (TikTok can take a minute to show it).
  let url = null;
  for (let i = 0; i < 12 && !url; i++) {
    const now = await videoIds(page).catch(() => []);
    const fresh = now.find((v) => !before.includes(v));
    if (fresh) url = `https://www.tiktok.com/@${handle}/video/${fresh}`;
    else await sleep(20000);
  }
  await browser.close();
  if (!url) { console.log('tiktok: posted, but the new link did not show on the profile yet'); process.exit(4); }
  console.log('tiktok_url: ' + url);
})().catch((e) => { console.log('tiktok: error - ' + e.message.slice(0, 300)); process.exit(1); });
