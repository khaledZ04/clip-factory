"""Submits posted clip links on the Content Rewards campaign page, like a person would:
open the page -> "Submit clip" -> paste link -> tick "I've read the requirements" -> "Submit clip".

Uses the sign-in saved by save-login.js (GitHub secret CR_SESSION). Never sees a password.
Usage: python submit.py <link> [<link> ...]   (env: CR_SESSION, CAMPAIGN_URL)
"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

CAMPAIGN = os.environ.get("CAMPAIGN_URL", "https://contentrewards.com/c/campaigns/e73e9e9c-fba4-4c8b-9c0e-6fb1e607c2a5")
SHOTS = "work"
os.makedirs(SHOTS, exist_ok=True)


def submit_one(page, link, n):
    page.goto(CAMPAIGN, wait_until="networkidle", timeout=90000)
    if page.get_by_role("button", name="Submit clip").count() == 0:
        page.screenshot(path="%s/submit-%d-nologin.png" % (SHOTS, n))
        raise SystemExit("LOGIN_EXPIRED: no Submit clip button - run save-login.js again")
    page.get_by_role("button", name="Submit clip").first.click()
    box = page.get_by_placeholder("tiktok.com", exact=False)
    box.wait_for(timeout=20000)
    box.fill(link)
    time.sleep(6)  # let the page run its three checks
    page.get_by_text("I've read the requirements", exact=False).click()
    time.sleep(1)
    page.screenshot(path="%s/submit-%d-before.png" % (SHOTS, n))
    dialog_btn = page.get_by_role("dialog").get_by_role("button", name="Submit clip")
    if dialog_btn.count() == 0:
        dialog_btn = page.get_by_role("button", name="Submit clip").last
    if os.environ.get("CHECK_ONLY") == "1":  # test mode: everything except the final click
        page.keyboard.press("Escape")
        return {"link": link, "ok": dialog_btn.count() > 0, "page_message": "check only - not submitted"}
    dialog_btn.click()
    time.sleep(6)
    page.screenshot(path="%s/submit-%d-after.png" % (SHOTS, n))
    still_open = page.get_by_placeholder("tiktok.com", exact=False).count() > 0
    errors = page.get_by_role("alert").all_inner_texts()
    return {"link": link, "ok": not still_open, "page_message": " | ".join(errors)[:300]}


def main():
    links = [l for l in sys.argv[1:] if l and l != "None"]
    state = json.loads(os.environ["CR_SESSION"])
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(storage_state=state, viewport={"width": 1280, "height": 900},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        page = ctx.new_page()
        for n, link in enumerate(links, 1):
            try:
                results.append(submit_one(page, link, n))
            except SystemExit:
                raise
            except Exception as e:
                page.screenshot(path="%s/submit-%d-error.png" % (SHOTS, n))
                results.append({"link": link, "ok": False, "page_message": str(e)[:300]})
        browser.close()
    print("submit:", json.dumps(results, ensure_ascii=False), flush=True)
    with open(os.path.join(SHOTS, "submit.json"), "w") as f:
        json.dump(results, f)
    if not all(r["ok"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
