# Apps Script Setup

How to deploy the Google Apps Script for the deletion tracking spreadsheet.

## Steps

1. Open the tracking spreadsheet:
   https://docs.google.com/spreadsheets/d/1USVdna-vwVaTrB-lgQdBE0oK_m4WKbJfnezgfLqGkME

2. Go to **Extensions → Apps Script**

3. Replace the contents of `Code.gs` with the contents of [`Code.gs`](Code.gs) from this folder

4. In the left sidebar, click the gear icon (**Project Settings**) and check **"Show 'appsscript.json' manifest file in editor"**

5. Switch back to the **Editor** (code icon), click `appsscript.json` in the file list, and replace its contents with [`appsscript_manifest.json`](appsscript_manifest.json) from this folder. This restricts the script's permissions to only the bound spreadsheet.

6. Click **Deploy → New deployment**

7. Configure:
   - Type: **Web app**
   - Execute as: **Me**
   - Who has access: **Anyone** (within the org) or **Anyone with the link**

8. Click **Deploy** and authorize when prompted — the prompt should only ask for access to *this* spreadsheet, not all spreadsheets

9. Copy the **Web app URL** — this is the value for `SHEETS_SCRIPT_URL` in your `.env` file or `--sheets-script-url` CLI argument

## Updating

If you change `Code.gs`, go to **Deploy → Manage deployments → Edit** and choose a **New version**, then click **Deploy**. The URL stays the same.

## Resume behaviour

When appending a row, the script checks if there is already a row with the same Env ID (column F) and a status of "In Progress" (column I). If found, it returns the existing row number instead of creating a duplicate. This allows the CLI to be safely re-run after interruptions (VPN drop, kubectl failure, aborted confirmation).

## Sheet columns

The script expects the first sheet to have these columns (A–K):

| Col | Field |
|-----|-------|
| A | Request Date |
| B | Ticket URL |
| C | Org ID |
| D | Project ID |
| E | Env Name |
| F | Env ID |
| G | Requester |
| H | Engineer / DSE |
| I | Status |
| J | Completed Date |
| K | New DDNA Env ID |
