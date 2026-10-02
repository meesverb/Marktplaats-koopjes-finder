/**
 * Koppeling tussen /flips (python dashboard.py --serve) en deze Google Sheet.
 * Plakken in Extensies -> Apps Script, zie SHEETS.md voor het stappenplan.
 *
 * De laptop roept deze webapp aan (Sheets kan niet bij de laptop):
 *   {secret, action: "pull"}               -> alle rijen van Flips, Klussen, Investeringen
 *   {secret, action: "push", sheets: {...}} -> die tabbladen (en Totalen, Aanbiedingen) opnieuw schrijven
 *
 * onEdit zet bij elke wijziging met de hand de kolom "bijgewerkt" van die rij
 * op nu. Zo weet flips_sheets.py wat er in de Sheet veranderde sinds de
 * vorige ronde, en wie van de twee het laatst was.
 *
 * De vijf tabbladen worden elke ronde overschreven (Aanbiedingen is alleen-lezen): eigen formules en
 * grafieken op een eigen tabblad, met verwijzingen als =Flips!H2 of
 * =SUMIF(Klussen!D:D;"onderdeel";Klussen!M:M).
 */

var SHEETS = ["Flips", "Klussen", "Investeringen", "Totalen", "Aanbiedingen"];
var EDITABLE = {
  Flips: ["fase", "doel_laag", "doel_hoog", "uren", "zoekwoorden", "verkooplink", "notitie"],
  Klussen: ["flip", "soort", "titel", "winkel", "geschat", "prijs", "bron", "investering", "tarief", "korting",
            "gedaan", "notitie"],
  Investeringen: ["soort", "titel", "winkel", "geschat", "prijs", "bron", "investering", "tarief", "korting",
                  "gedaan", "notitie"],
};
var CHOICES = {
  fase: ["voorraad", "gekocht", "opknappen", "te_koop"],
  soort: ["onderdeel", "klus", "reis"],
  investering: ["ja", "nee"],
  gedaan: ["ja", "nee"],
  korting: ["vol", "40", "gratis"],
  bron: ["gecontroleerd", "schatting"],
};
// Als tekst bewaren, anders maakt Sheets er een datum van in de eigen tijdzone.
var TEXT_COLUMNS = ["bijgewerkt", "gekocht_op", "verkocht_op", "korting", "bekeken"];

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var body = JSON.parse(e.postData.contents);
    var secret = PropertiesService.getScriptProperties().getProperty("SECRET");
    if (!secret || body.secret !== secret) return reply({ok: false, error: "verkeerde sleutel"});
    if (body.action === "pull") return reply({ok: true, sheets: pull()});
    if (body.action === "push") { push(body.sheets); return reply({ok: true}); }
    return reply({ok: false, error: "onbekende actie"});
  } catch (err) {
    return reply({ok: false, error: String(err)});
  } finally {
    lock.releaseLock();
  }
}

function reply(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function pull() {
  var out = {};
  var book = SpreadsheetApp.getActiveSpreadsheet();
  ["Flips", "Klussen", "Investeringen"].forEach(function (name) {
    var sheet = book.getSheetByName(name);
    if (!sheet || sheet.getLastRow() < 2) { out[name] = []; return; }
    var values = sheet.getDataRange().getValues();
    var headers = values[0];
    out[name] = values.slice(1).map(function (row) {
      var item = {};
      headers.forEach(function (h, i) {
        var v = row[i];
        item[h] = v instanceof Date ? v.toISOString() : v;
      });
      return item;
    }).filter(function (item) {
      return Object.keys(item).some(function (k) { return item[k] !== ""; });
    });
  });
  return out;
}

function push(sheets) {
  var book = SpreadsheetApp.getActiveSpreadsheet();
  SHEETS.forEach(function (name) {
    var data = sheets[name];
    if (!data) return;
    var sheet = book.getSheetByName(name) || book.insertSheet(name);
    sheet.clear();
    sheet.getDataRange().clearDataValidations();
    var headers = data.headers;
    var rows = data.rows.map(function (r) { return r.map(function (v) { return v === null ? "" : v; }); });
    var width = headers.length;
    var height = rows.length + 1;
    TEXT_COLUMNS.forEach(function (col) {
      var i = headers.indexOf(col);
      if (i >= 0) sheet.getRange(1, i + 1, Math.max(height, 200), 1).setNumberFormat("@");
    });
    sheet.getRange(1, 1, 1, width).setValues([headers]).setFontWeight("bold");
    if (rows.length) sheet.getRange(2, 1, rows.length, width).setValues(rows);
    sheet.setFrozenRows(1);
    var editable = EDITABLE[name] || [];
    headers.forEach(function (h, i) {
      var range = sheet.getRange(2, i + 1, Math.max(rows.length, 1) + 50, 1);
      if (editable.indexOf(h) < 0) range.setBackground("#f1f1ef");
      if (CHOICES[h] && editable.indexOf(h) >= 0) {
        range.setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(CHOICES[h], true)
          .setAllowInvalid(false).build());
      }
      if (/^(inkoop|uitgegeven|gepland|doel_|winst|hoogste_bod|verkocht_voor|per_uur|geschat|prijs|tarief|kost|verzending|totaal)/
          .test(h)) range.setNumberFormat("€ #,##0.00");
    });
    var idCol = headers.indexOf("id");
    if (idCol >= 0) sheet.hideColumns(idCol + 1);
    var stamp = headers.indexOf("bijgewerkt");
    if (stamp >= 0) sheet.hideColumns(stamp + 1);
  });
}

function onEdit(e) {
  var sheet = e.range.getSheet();
  var name = sheet.getName();
  if (!EDITABLE[name] || e.range.getRow() < 2) return;
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var col = headers.indexOf("bijgewerkt");
  if (col < 0 || e.range.getColumn() === col + 1) return;
  var now = new Date().toISOString();
  var stamps = [];
  for (var i = 0; i < e.range.getNumRows(); i++) stamps.push([now]);
  sheet.getRange(e.range.getRow(), col + 1, e.range.getNumRows(), 1).setValues(stamps);
}
