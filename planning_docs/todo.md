# Environment Reset Tool - Programmatic TODO

Tasks identified by comparing the [Game Data Deletion handbook](Game%20Data%20Deletion%20_%20Unity%20Analytics%202.0%20Handbook.htm) against the current codebase.

The core deletion flow (Zendesk -> Sheets -> API key -> POST deletion -> update Sheets) is already wired up. The items below cover remaining gaps.

---

## High Priority

### 1. ✔️ Add `serviceHelpers` (hex_helpers) to requirements.txt
`zendesk_client.py` imports `from serviceHelpers.zendesk import zendesk` but `requirements.txt` only lists `pytest` and `requests`. The hex_helpers / serviceHelpers package must be added as a dependency.

**File:** `requirements.txt`

---

### 2. ✔️ Add authentication to `fetch_environments()` in main.py
`main.py:96` `fetch_environments()` calls the Unity Services API (`services.unity.com`) with no auth headers. This likely needs a bearer token or service account auth to work. The planning doc implies you need VPN + credentials.

**File:** `main.py` — `fetch_environments()`

---

### 3. ✔️ Create Google Apps Script for Sheets integration
`SheetsClient` sends POST requests to a `SHEETS_SCRIPT_URL` expecting an Apps Script web app that can:

1. **Append** a row with pre-deletion data (`action: "append"`) and return `{"row": N}`
2. **Update** a row's status, completed_date, and new_ddna_env_id (`action: "update"`)

This Apps Script needs to be created and deployed against the tracking spreadsheet at:
https://docs.google.com/spreadsheets/d/1USVdna-vwVaTrB-lgQdBE0oK_m4WKbJfnezgfLqGkME

**Deliverable:** Google Apps Script code + deployment instructions

---

## Medium Priority

### 4. Add Slack notification to #devs-curiosity
The planning doc requires posting to `#devs-curiosity` (Slack channel `CTT3XTDKJ`) before performing a deletion and if a deletion fails. Currently no Slack integration exists.

Options: use a Slack webhook URL or Slack API with a bot token. Should post:
1. Pre-deletion notice with env ID
2. Post-deletion success or failure message

**New file:** `slack_client.py` (+ tests)
**Modified:** `main.py` — integrate calls before/after deletion

---

### 5. ✔️ Add VPN connectivity check before deletion
The planning doc says "Be on the VPN" as a prerequisite. The auto-provisioning service is at `loh-analytics-auto-provisioning.prd.mz.internal.unity3d.com` (internal domain).

Add a connectivity check early in the flow (e.g., DNS resolution or a lightweight health check) and give a clear error message if the VPN is not connected.

**File:** `main.py` — add check before Step 5 (deletion)

---

### 6. Add rollback functionality
The planning doc describes manual rollback steps when something goes wrong. Implement a `--rollback` mode or separate command that reverses the environment-id swap in the `environments` table:

1. Set `unity_environment_id` back on the old env, null on new env
2. Restore `name` and `unity_environment_name`
3. Set `deleted=0` on old env, `deleted=1` on new env

This requires knowing the old and new DDNA env IDs.

**File:** `main.py` — new CLI subcommand or `--rollback` flag
**File:** `deletion_client.py` — new rollback method (if API supports it)

---

### 7. Validate environment exists before deletion
Currently `main.py` proceeds directly to the deletion POST without verifying that the env ID is valid. Add a pre-flight check that confirms the environment exists and shows the environment name/details for user confirmation, especially when `--env-id` is passed via CLI rather than the interactive picker.

**File:** `main.py` — add validation between Steps 3 and 4

---

## Low Priority

### 8. Fix `ticket.url` to return agent URL, not API URL
`zendesk_client.py:57` uses `ticket.url` to populate the spreadsheet. Depending on the hex_helpers zendesk implementation, `.url` may return the API URL (e.g., `https://unity3d.zendesk.com/api/v2/tickets/12345.json`) rather than the agent UI URL (`https://unity3d.zendesk.com/agent/tickets/12345`).

Verify and fix if needed so the spreadsheet gets a clickable agent link.

**File:** `zendesk_client.py` — `get_ticket_data()`

---

### 9. Add gcloud cluster credentials setup helper
The planning doc shows a prerequisite:
```
gcloud container clusters get-credentials unity-loh-prd-3-euw1 \
  --region europe-west1 --project unity-ads-liveopshub-prd
```

`get_api_key_from_kubectl()` assumes kubectl is already pointed at the right cluster. Consider adding an `--auto-gcloud` flag or a check that runs the gcloud credentials command if kubectl fails.

**File:** `main.py` — `get_api_key_from_kubectl()`

---

### 10. ✔️ Add resume support for in-progress deletions
When appending a row, the Apps Script should first check if there is already a row with the same Env ID (column F) and a status of "In Progress" (column I). If a match is found, return the existing row number instead of creating a duplicate.

This allows the CLI to be re-run against the same Zendesk ticket + environment without duplicating the spreadsheet entry — e.g. after a VPN drop, kubectl failure, or aborted confirmation.

**Changes needed:**
- `apps_script/Code.gs` — `handleAppend()`: search for existing row by env ID + status before appending
- `sheets_client.py` — no changes needed (already uses the returned `row` index)

---

### 11. Add tests for `main()` orchestration flow
`test_main.py` only tests `extract_ticket_id()`. The main orchestration logic (Zendesk fetch -> Sheets log -> deletion -> Sheets update) has no integration-level tests.

Add tests that mock the clients and verify the end-to-end flow, including:
- Dry-run mode
- Skip-sheets mode
- Missing environment variables
- Environment selection flow

**File:** `tests/test_main.py`
