const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
  let events, dialog, downloaded;
  const calls = [], messages = [], alerts = [];
  const escape = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const wrapper = () => {
    const w = {content: '', html(value) { w.content = value; }, find: () => ({each: () => {}})};
    return w;
  };
  class Dialog {
    constructor(options) {
      this.options = options;
      this.fields_dict = {};
      for (const f of options.fields) this.fields_dict[f.fieldname] = {$wrapper: wrapper(), $input: {on: () => {}}};
      dialog = this;
    }
    get_value() { return ''; }
    show() { this.shown = true; }
  }
  const frappe = {
    utils: {escape_html: escape},
    ui: {form: {on: (name, handlers) => { events = handlers; }}, Dialog},
    datetime: {get_today: () => '2026-10-23', add_months: (day, n) => (n === -12 ? '2025-10-23' : day)},
    defaults: {get_user_default: () => 'Vortexus'},
    call: async args => { calls.push(args); return {message: {added: 3, not_added: 0, limit: 500}}; },
    msgprint: message => messages.push(message),
    show_alert: alert => alerts.push(alert),
  };
  const context = {
    frappe, Intl, console, __: (text, args) => (args || []).reduce((t, a, i) => t.replace(`{${i}}`, a), text),
    Blob: class { constructor(parts) { downloaded = parts.join(''); } },
    URL: {createObjectURL: () => 'blob:x', revokeObjectURL: () => {}},
    document: {createElement: () => ({click() {}})},
  };
  vm.runInNewContext(fs.readFileSync('vortexus_discount_matrix/public/js/simulation.js', 'utf8'), context);

  let html = '';
  const buttons = {};
  const groups = [
    {customer_group: 'Dealers', column: 'Dealers', qty: 10, history_price: 80, history_discount: 20, max_discount: 50, assumed_discount: 20,
      expected_price: 80, expected_margin: 50, projected_revenue: 800, projected_profit: 400, floor_price: 50, floor_margin: 20, min_margin: 30},
    {customer_group: 'Distributor, East', column: 'Dealers', qty: 0, max_discount: 50, assumed_discount: 50, expected_price: 50,
      expected_margin: 20, projected_revenue: 0, projected_profit: 0, floor_price: 50, floor_margin: 20, min_margin: 30},
    {customer_group: 'Traders', column: 'Traders', qty: 0, max_discount: 40, assumed_discount: 40, expected_price: 60,
      expected_margin: 33.3, projected_revenue: 0, projected_profit: 0, floor_price: 60, floor_margin: 33.3},
  ];
  const frm = {
    doc: {name: 'VDM-SIM-1', title: 'Test', projection_basis: 'Historical discount', projected_revenue: 800, projected_profit: 400,
      projected_margin: 50, history_profit: 400, history_revenue: 800, items: [{item_code: '<b>P1</b>', item_name: 'Pump', proposed_price: 100,
      current_price: 100, price_change: 0, cost: 40, cost_source: 'Item Valuation Rate', projected_profit: 400,
      projected_margin: 50, warnings: 'Dealers: below minimum', column_detail: JSON.stringify(groups)}]},
    fields_dict: {results_html: {$wrapper: {html: value => { html = value; }}}},
    is_new: () => false, is_dirty: () => false, save: async () => { frm.saved = true; }, reload_doc: async () => {},
    add_custom_button: (label, action) => { buttons[label] = action; },
  };

  events.refresh(frm);
  assert.ok(html.includes('Customer Group') && html.includes('Matrix Column') && html.includes('Distributor, East'));
  assert.equal((html.match(/table-warning/g) || []).length, 2, 'both Dealers-column groups break the 30% minimum');
  assert.ok(html.includes('&lt;b&gt;P1&lt;/b&gt;') && !html.includes('<b>P1</b>'), 'item code escaped');
  assert.ok(html.includes('Dealers: below minimum'));
  assert.ok(html.includes('800.00') && html.includes('50.0%'));
  assert.deepEqual(Object.keys(buttons), ['Preview', 'Load Items', 'Recalculate']);

  await buttons.Preview();
  assert.ok(dialog.shown);
  assert.equal(dialog.options.size, 'extra-large');
  const table = dialog.fields_dict.table.$wrapper.content;
  assert.equal((table.match(/<tr/g) || []).length, 4, 'header plus one row per item and customer group');
  assert.ok(table.includes('Cost Source') && table.includes('Item Valuation Rate') && table.includes('Price at Max Discount'));
  assert.ok(!table.includes('<b>P1</b>'));
  assert.ok(dialog.fields_dict.summary.$wrapper.content.includes('3 rows'));
  dialog.options.primary_action();
  const csvLines = downloaded.replace(/^﻿/, '').split('\r\n');
  assert.equal(csvLines.length, 4);
  assert.ok(csvLines[0].startsWith('Item,Item Name,Item Group,Current Price'));
  assert.ok(csvLines[2].includes('"Distributor, East"'), 'CSV quotes commas');
  assert.ok(csvLines[1].startsWith('<b>P1</b>,Pump'));

  frm.doc.items = [];
  await buttons.Preview();
  assert.ok(messages.pop().includes('Add items first'));

  frm.doc.items = [{item_code: 'P2', column_detail: '{bad'}];
  events.refresh(frm);
  assert.ok(html.includes('could not be read'));

  await buttons['Load Items']();
  assert.equal(calls[0].method, 'vortexus_discount_matrix.simulation.load_items');
  assert.equal(JSON.stringify(calls[0].args), JSON.stringify({name: 'VDM-SIM-1'}));
  assert.ok(messages[0].includes('Added 3 items'));

  frm.saved = false;
  Object.assign(frm.doc, {item_group: 'CATRIDGES', company: 'Vortexus', from_date: '2026-01-01', to_date: '2026-10-23'});
  await events.item_group(frm);
  assert.ok(frm.saved, 'selecting an Item Group saves so the server loads its items');
  assert.ok(alerts[0].message.includes('CATRIDGES'));
  frm.saved = false;
  frm.doc.item_group = '';
  await events.item_group(frm);
  assert.ok(!frm.saved);

  frm.doc.items = [];
  events.refresh(frm);
  assert.ok(html.includes('Load Item Group'));

  const values = {};
  const fresh = {doc: {}, is_new: () => true, set_value: (k, v) => { values[k] = v; }};
  events.onload(fresh);
  assert.equal(JSON.stringify(values), JSON.stringify({to_date: '2026-10-23', from_date: '2025-10-23', company: 'Vortexus'}));
  console.log('Price simulation form checks passed: customer groups, preview, CSV, Item Group loading and defaults.');
})().catch(error => { console.error(error); process.exitCode = 1; });
