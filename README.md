# clip-factory

Makes the next 1-minute part for the n8n workflow **مصنع الكليبينق** 10 times a day (10 AM to 10 PM Riyadh).
No AI picks or edits anything: each episode is cut into consecutive 1-minute parts, with the watermark,
a small title on top and Arabic captions.

- Runs: `.github/workflows/clip.yml` (Actions tab → "Make next clip" → Run workflow; tick *dry run* to test).
- Finished clips: the **clips** release (kept 7 days).
- Secrets: `N8N_NEXT_URL`, `N8N_READY_URL` (n8n webhooks), optional `YT_COOKIES` if YouTube blocks downloads.
