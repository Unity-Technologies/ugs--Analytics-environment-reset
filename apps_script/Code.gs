/**
 * Google Apps Script web app for the deletion tracking spreadsheet.
 *
 * Deployed as: Web app → Execute as "Me" → Access "Anyone with link"
 *
 * Supports two actions via POST JSON:
 *
 * 1. Append a row (pre-deletion):
 *    { "action": "append", "row": ["date", "ticket_url", ...] }
 *    → returns { "row": <1-based row number>, "url": <spreadsheet url>, "gid": <sheet gid> }
 *
 * 2. Update a row (post-deletion):
 *    { "action": "update", "row_index": 5, "updates": { "status": "Done", ... } }
 *    → returns { "ok": true }
 *
 * Expected sheet columns (A-K):
 *   A: Request Date
 *   B: Ticket URL
 *   C: Org ID
 *   D: Project ID
 *   E: Env Name
 *   F: Env ID
 *   G: Requester
 *   H: Engineer / DSE
 *   I: Status
 *   J: Completed Date
 *   K: New DDNA Env ID
 */

// Column indices (1-based).
var COL_ENV_ID = 6;          // F
var COL_STATUS = 9;          // I
var COL_COMPLETED_DATE = 10; // J
var COL_NEW_DDNA_ENV_ID = 11; // K

/**
 * Handle POST requests from the deletion CLI tool.
 */
function doPost(e) {
  var payload = JSON.parse(e.postData.contents);
  var action = payload.action;

  if (action === "append") {
    return handleAppend(payload);
  } else if (action === "update") {
    return handleUpdate(payload);
  } else {
    return jsonResponse({ error: "Unknown action: " + action }, 400);
  }
}

/**
 * Append a new row to the first sheet, or return an existing in-progress row
 * for the same environment ID.
 *
 * Expects payload.row to be an array of 11 values (columns A-K).
 * Returns the 1-based row number and whether the row already existed:
 *   { "row": N, "resumed": false, "url": ..., "gid": ... }  — new row appended
 *   { "row": N, "resumed": true,  "url": ..., "gid": ... }  — existing in-progress row found
 */
function handleAppend(payload) {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getSheets()[0];
  var row = payload.row;

  if (!row || !Array.isArray(row)) {
    return jsonResponse({ error: "Missing or invalid 'row' array." }, 400);
  }

  var sheetMeta = { url: spreadsheet.getUrl(), gid: sheet.getSheetId() };

  // Check for an existing row with the same env ID and "In Progress" status.
  var envId = row[COL_ENV_ID - 1]; // 0-based index
  if (envId) {
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      var envIds = sheet.getRange(2, COL_ENV_ID, lastRow - 1, 1).getValues();
      var statuses = sheet.getRange(2, COL_STATUS, lastRow - 1, 1).getValues();
      for (var i = 0; i < envIds.length; i++) {
        if (envIds[i][0] === envId && statuses[i][0] === "In Progress") {
          return jsonResponse({ row: i + 2, resumed: true, url: sheetMeta.url, gid: sheetMeta.gid });
        }
      }
    }
  }

  sheet.appendRow(row);
  var lastRow = sheet.getLastRow();

  return jsonResponse({ row: lastRow, resumed: false, url: sheetMeta.url, gid: sheetMeta.gid });
}

/**
 * Update specific cells in an existing row.
 * Expects payload.row_index (1-based) and payload.updates object with keys:
 *   - status         → column I
 *   - completed_date → column J
 *   - new_ddna_env_id → column K
 */
function handleUpdate(payload) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  var rowIndex = payload.row_index;
  var updates = payload.updates;

  if (!rowIndex || !updates) {
    return jsonResponse({ error: "Missing 'row_index' or 'updates'." }, 400);
  }

  if (updates.status !== undefined) {
    sheet.getRange(rowIndex, COL_STATUS).setValue(updates.status);
  }
  if (updates.completed_date !== undefined) {
    sheet.getRange(rowIndex, COL_COMPLETED_DATE).setValue(updates.completed_date);
  }
  if (updates.new_ddna_env_id !== undefined) {
    sheet.getRange(rowIndex, COL_NEW_DDNA_ENV_ID).setValue(updates.new_ddna_env_id);
  }

  return jsonResponse({ ok: true });
}

/**
 * Return a JSON ContentService response.
 */
function jsonResponse(data, statusCode) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
