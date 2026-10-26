/**
 * Nick's Stock Desk
 *
 * Desk menu:
 *   Refresh data now
 *   Install hourly auto-refresh
 *   Remove auto-refresh
 *
 * Copies each data/*.csv from GitHub into the tab of the same name.
 * Does not use IMPORTDATA. Does not place trades.
 *
 * score_history.csv is the job's memory for last week's score. It is not a page.
 */
var BASE = 'https://raw.githubusercontent.com/PatelNicknp/nicks-stock-desk/main/data/';

var TABS = [
  'scores', 'score_details', 'market_today', 'sectors', 'breadth_history',
  'alerts', 'score_changes', 'portfolio', 'portfolio_summary', 'watchlist',
  'prices', 'news', 'scanner_growth', 'scanner_quality', 'scanner_dividend', 'scanner_wheel',
  'scanner_vcp', 'scanner_canslim', 'scanner_box', 'scanner_breakdown', 'scanner_volume', 'scanner_flag', 'scanner_leaders', 'scanner_52w',
  'highs_lows_history', 'buy_setups', 'options_ideas', 'options_skipped',
  'earnings_calendar', 'earnings_heatmap', 'earnings_cards', 'earnings_history',
  'put_call', 'option_walls', 'analyst_ratings', 'institutional_13f', 'aaii_sentiment',
  'insider_trading', 'headline_sentiment', 'xly_xlp',
  'financials_summary', 'earnings_tracker', 'company_financials', 'dividend_scanner',
  'macro_screener', 'sector_macro', 'sector_rotation', 'sector_rotation_tails', 'sector_rotation_history', 'historical_pe',
  'breakouts', 'trends', 'pullbacks', 'gainers_losers', 'sector_performance', 'heatmaps',
  'freshness', 'updates_log', 'help', 'settings', 'universe',
  'backtest_summary', 'backtest_buckets', 'backtest_equity', 'backtest_yearly', 'backtest_notes'
];

// These take longer to write. Give them a batch of their own.
var LARGE = {
  prices: true,
  score_details: true,
  earnings_history: true,
  earnings_tracker: true,
  company_financials: true,
  option_walls: true,
  financials_summary: true,
  sector_rotation_history: true
};

// Stay under Google's 10 million cell cap, with room for the Setup tab.
var CELL_CAP = 9000000;
// Leave the execution before the 6 minute limit and finish the current tab first.
var BUDGET_MS = 4.5 * 60 * 1000;
var BATCH_SIZE = 8;
var WRITE_CHUNK = 5000;

var PROP_INDEX = 'DESK_INDEX';
var PROP_FILES = 'DESK_FILES';
var PROP_ERRORS = 'DESK_ERRORS';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Desk')
    .addItem('Refresh data now', 'refreshNow')
    .addItem('Install hourly auto-refresh', 'installHourly')
    .addItem('Remove auto-refresh', 'removeHourly')
    .addToUi();
}

function refreshNow() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) {
    toast('A refresh is already running. The Setup tab shows how far it got.');
    return;
  }
  try {
    var props = PropertiesService.getScriptProperties();
    props.setProperty(PROP_INDEX, '0');
    props.setProperty(PROP_FILES, TABS.join(','));
    props.setProperty(PROP_ERRORS, '');
    deleteTriggers('continueRefresh');
    runRefresh();
  } finally {
    lock.releaseLock();
  }
}

function installHourly() {
  deleteTriggers('refreshNow');
  ScriptApp.newTrigger('refreshNow').timeBased().everyHours(1).create();
  writeStatus('Hourly refresh is on. The sheet reloads about once an hour. You can still use Refresh data now.');
  toast('Hourly refresh is on.');
}

function removeHourly() {
  deleteTriggers('refreshNow');
  writeStatus('Hourly refresh is off. Use Desk > Refresh data now when you want the latest files.');
  toast('Hourly refresh is off.');
}

function continueRefresh() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) {
    return;
  }
  try {
    runRefresh();
  } finally {
    lock.releaseLock();
  }
}

function runRefresh() {
  var started = Date.now();
  var props = PropertiesService.getScriptProperties();
  var files = (props.getProperty(PROP_FILES) || TABS.join(',')).split(',');
  var index = parseInt(props.getProperty(PROP_INDEX) || '0', 10);
  if (isNaN(index) || index < 0) index = 0;
  var ss = SpreadsheetApp.getActive();
  var errors = props.getProperty(PROP_ERRORS) || '';

  while (index < files.length) {
    var need = LARGE[files[index]] ? 150000 : 30000;
    if (Date.now() - started + need > BUDGET_MS) {
      props.setProperty(PROP_INDEX, String(index));
      props.setProperty(PROP_ERRORS, errors);
      scheduleContinuation();
      writeStatus('Still working. Paused at ' + files[index] + ' (' + index + ' of ' + files.length + ' done). It will continue on its own in about a minute.');
      return;
    }
    var batch = nextBatch(files, index);
    var loaded = fetchBatch(batch);
    for (var b = 0; b < batch.length; b++) {
      var name = batch[b];
      var got = loaded[b];
      try {
        if (got.error) {
          errors = addError(errors, got.error);
          writeStatus('Problem on ' + name + '. Older rows on that tab were left in place. ' + (index + b + 1) + ' of ' + files.length + '.');
        } else {
          var note = writeTab(ss, name, got.rows);
          if (note) errors = addError(errors, note);
          writeStatus('Loaded ' + name + ' (' + (index + b + 1) + ' of ' + files.length + ').');
        }
      } catch (err) {
        errors = addError(errors, name + ' was not written (' + err + ')');
        writeStatus('Problem on ' + name + '. ' + (index + b + 1) + ' of ' + files.length + '.');
      }
      SpreadsheetApp.flush();
    }
    index += batch.length;
    props.setProperty(PROP_INDEX, String(index));
    props.setProperty(PROP_ERRORS, errors);
  }

  deleteTriggers('continueRefresh');
  props.deleteProperty(PROP_INDEX);
  props.deleteProperty(PROP_FILES);
  props.deleteProperty(PROP_ERRORS);
  var cells = gridCells(ss);
  var summary = 'Updated ' + files.length + ' tabs. About ' + cells + ' cells in this sheet.';
  if (errors) summary += ' Problems: ' + errors;
  else summary += ' No problems.';
  writeStatus(summary);
  toast(errors ? 'Refresh finished with problems. See the Setup tab.' : 'Refresh finished.');
}

function nextBatch(files, index) {
  if (LARGE[files[index]]) return [files[index]];
  var batch = [];
  var i = index;
  while (i < files.length && batch.length < BATCH_SIZE && !LARGE[files[i]]) {
    batch.push(files[i]);
    i++;
  }
  return batch;
}

function fetchBatch(names) {
  var requests = [];
  for (var i = 0; i < names.length; i++) {
    requests.push({
      url: BASE + names[i] + '.csv?_=' + Date.now(),
      muteHttpExceptions: true,
      headers: { 'Cache-Control': 'no-cache' }
    });
  }
  var responses;
  try {
    responses = UrlFetchApp.fetchAll(requests);
  } catch (err) {
    responses = [];
    for (var j = 0; j < names.length; j++) {
      try {
        responses.push(UrlFetchApp.fetch(requests[j].url, {
          muteHttpExceptions: true,
          headers: { 'Cache-Control': 'no-cache' }
        }));
      } catch (one) {
        responses.push(null);
      }
    }
  }
  var out = [];
  for (var k = 0; k < names.length; k++) {
    out.push(parseResponse(names[k], responses[k]));
  }
  return out;
}

function parseResponse(name, resp) {
  if (!resp) return { error: name + ' could not be downloaded' };
  try {
    var code = resp.getResponseCode();
    if (code !== 200) return { error: name + ' returned HTTP ' + code };
    var text = resp.getContentText() || '';
    if (!text.replace(/\s/g, '')) return { error: name + ' was empty' };
    var rows = dropTrailingBlank(rectangular(Utilities.parseCsv(text)));
    if (!rows.length) return { error: name + ' had no rows' };
    return { rows: rows.map(coerceRow) };
  } catch (err) {
    return { error: name + ' could not be read (' + err + ')' };
  }
}

function writeTab(ss, name, rows) {
  var sheet = ss.getSheetByName(name);
  if (!sheet) sheet = ss.insertSheet(name);
  var cols = rows[0].length;
  var room = CELL_CAP - otherCells(ss, sheet);
  var maxRows = Math.floor(room / Math.max(cols, 1));
  var note = '';
  if (maxRows < 1) {
    return name + ' was skipped so the sheet stays under 10 million cells';
  }
  if (rows.length > maxRows) {
    rows = rows.slice(0, maxRows);
    note = name + ' was cut to ' + maxRows + ' rows so the sheet stays under 10 million cells';
  }
  fitGrid(sheet, rows.length, cols);
  for (var i = 0; i < rows.length; i += WRITE_CHUNK) {
    var part = rows.slice(i, i + WRITE_CHUNK);
    sheet.getRange(i + 1, 1, part.length, cols).setValues(part);
  }
  return note;
}

function fitGrid(sheet, rows, cols) {
  var maxCols = sheet.getMaxColumns();
  if (maxCols > cols) sheet.deleteColumns(cols + 1, maxCols - cols);
  else if (maxCols < cols) sheet.insertColumnsAfter(maxCols, cols - maxCols);
  var maxRows = sheet.getMaxRows();
  if (maxRows > rows) sheet.deleteRows(rows + 1, maxRows - rows);
  else if (maxRows < rows) sheet.insertRowsAfter(maxRows, rows - maxRows);
}

function otherCells(ss, sheet) {
  var n = 0;
  var id = sheet.getSheetId();
  var all = ss.getSheets();
  for (var i = 0; i < all.length; i++) {
    if (all[i].getSheetId() === id) continue;
    n += all[i].getMaxRows() * all[i].getMaxColumns();
  }
  return n;
}

function gridCells(ss) {
  var n = 0;
  var all = ss.getSheets();
  for (var i = 0; i < all.length; i++) {
    n += all[i].getMaxRows() * all[i].getMaxColumns();
  }
  return n;
}

function rectangular(rows) {
  var width = 0;
  var i;
  for (i = 0; i < rows.length; i++) {
    if (rows[i].length > width) width = rows[i].length;
  }
  if (!width) width = 1;
  var out = [];
  for (i = 0; i < rows.length; i++) {
    var row = rows[i].slice();
    while (row.length < width) row.push('');
    out.push(row);
  }
  return out;
}

function dropTrailingBlank(rows) {
  while (rows.length > 1) {
    var last = rows[rows.length - 1];
    var blank = true;
    for (var i = 0; i < last.length; i++) {
      if (last[i] !== '' && last[i] !== null) {
        blank = false;
        break;
      }
    }
    if (!blank) break;
    rows = rows.slice(0, -1);
  }
  return rows;
}

function coerceRow(row) {
  var out = [];
  for (var i = 0; i < row.length; i++) out.push(coerce(row[i]));
  return out;
}

function coerce(value) {
  if (value === null || value === undefined) return '';
  var text = String(value);
  if (text === '') return '';
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text);
  return text;
}

function writeStatus(line) {
  var ss = SpreadsheetApp.getActive();
  var sheet = ss.getSheetByName('Setup');
  if (!sheet) {
    sheet = ss.insertSheet('Setup', 0);
    sheet.getRange('A1').setValue("Nick's Stock Desk");
    sheet.getRange('A2').setValue('Research only. This sheet does not place trades.');
  }
  var current = String(sheet.getRange('A3').getValue() || '');
  if (!current || current.indexOf('IMPORTDATA') !== -1) {
    sheet.getRange('A3').setValue('Tabs are filled by Desk > Refresh data now. This sheet does not use IMPORTDATA.');
  }
  var tz = ss.getSpreadsheetTimeZone() || 'America/Los_Angeles';
  sheet.getRange('A6').setValue('Last refresh');
  sheet.getRange('B6').setValue(Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss'));
  sheet.getRange('A7').setValue('Status');
  sheet.getRange('B7').setValue(line);
}

function addError(errors, message) {
  var next = errors ? errors + ' | ' + message : message;
  if (next.length > 1800) next = next.slice(0, 1800);
  return next;
}

function scheduleContinuation() {
  deleteTriggers('continueRefresh');
  ScriptApp.newTrigger('continueRefresh').timeBased().after(60 * 1000).create();
}

function deleteTriggers(handler) {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === handler) ScriptApp.deleteTrigger(triggers[i]);
  }
}

function toast(message) {
  try {
    SpreadsheetApp.getActive().toast(message);
  } catch (err) {
    // A timed trigger has no screen. The Setup tab still has the status.
  }
}
