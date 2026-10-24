/**
 * Nick's Stock Desk
 * Adds a menu: Desk > Refresh data now
 * and Desk > Set up data tabs (first time only).
 *
 * The script does not place trades. It only reloads the published CSV files.
 */
var BASE = 'https://raw.githubusercontent.com/PatelNicknp/nicks-stock-desk/main/data/';

var TABS = [
  'scores', 'score_details', 'market_today', 'sectors', 'breadth_history',
  'alerts', 'score_changes', 'portfolio', 'portfolio_summary', 'watchlist',
  'prices', 'news', 'scanner_growth', 'scanner_quality', 'scanner_dividend', 'scanner_wheel',
  'scanner_vcp', 'scanner_canslim', 'scanner_box', 'scanner_flag', 'scanner_leaders',
  'earnings_calendar', 'earnings_heatmap', 'earnings_cards', 'earnings_history',
  'put_call', 'option_walls', 'analyst_ratings', 'institutional_13f', 'aaii_sentiment',
  'insider_trading', 'headline_sentiment', 'xly_xlp',
  'financials_summary', 'earnings_tracker', 'company_financials', 'dividend_scanner',
  'macro_screener', 'sector_macro', 'historical_pe',
  'breakouts', 'trends', 'pullbacks', 'gainers_losers', 'sector_performance', 'heatmaps',
  'freshness', 'updates_log', 'help', 'settings', 'universe',
  'backtest_summary', 'backtest_buckets', 'backtest_equity', 'backtest_yearly', 'backtest_notes'
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Desk')
    .addItem('Refresh data now', 'refreshNow')
    .addItem('Set up data tabs', 'setupTabs')
    .addToUi();
}

function setupTabs() {
  var ss = SpreadsheetApp.getActive();
  TABS.forEach(function (name) {
    var sheet = ss.getSheetByName(name) || ss.insertSheet(name);
    sheet.clear();
    sheet.getRange('A1').setFormula(formulaFor(name));
  });
  SpreadsheetApp.getActive().toast('Data tabs are ready.');
}

function refreshNow() {
  var ss = SpreadsheetApp.getActive();
  var stamp = Date.now();
  TABS.forEach(function (name) {
    var sheet = ss.getSheetByName(name);
    if (!sheet) return;
    sheet.getRange('A1').setFormula(formulaFor(name, stamp));
  });
  SpreadsheetApp.flush();
  Utilities.sleep(4000);
  TABS.forEach(function (name) {
    var sheet = ss.getSheetByName(name);
    if (!sheet) return;
    sheet.getRange('A1').setFormula(formulaFor(name));
  });
  ss.toast('Reload started. Give the sheet a minute, then refresh the Looker report.');
}

function formulaFor(name, stamp) {
  var url = BASE + name + '.csv';
  if (stamp) url += '?_=' + stamp;
  return '=IMPORTDATA("' + url + '")';
}
