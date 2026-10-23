const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
  let events;
  const calls = [], messages = [], values = {};
  const escape = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const frappe = {
    utils: {escape_html: escape},
    ui: {form: {on: (name, handlers) => { events = handlers; }}},
    datetime: {get_today: () => '2026-10-23', add_months: (day, n) => (n === -12 ? '2025-10-23' : day)},
    defaults: {get_user_default: () => 'Vortexus'},
    call: async args => { calls.push(args); return {message: {added: 3, not_added: 0, limit: 500}}; },
    msgprint: message => messages.push(message),
  };
  vm.runInNewContext(fs.readFileSync('vortexus_discount_matrix/public/js/simulation.js', 'utf8'), {
    frappe, Intl, __: (text, args) => (args || []).reduce((t, a, i) => t.replace(`{${i}}`, a), text), console,
  });

  let html = '';
  const buttons = {};
  const columns = [
    {column: 'Dealers', qty: 10, history_price: 80, history_discount: 20, max_discount: 50, assumed_discount: 20,
      expected_price: 80, expected_margin: 50, projected_revenue: 800, projected_profit: 400, floor_price: 50, floor_margin: 20, min_margin: 30},
    {column: 'Traders', qty: 0, max_discount: 40, assumed_discount: 40, expected_price: 60, expected_margin: 33.3,
      projected_revenue: 0, projected_profit: 0, floor_price: 60, floor_margin: 33.3},
  ];
  const frm = {
    doc: {name: 'VDM-SIM-1', projection_basis: 'Historical discount', projected_revenue: 800, projected_profit: 400,
      projected_margin: 50, history_profit: 400, items: [{item_code: '<b>P1</b>', item_name: 'Pump', proposed_price: 100,
      current_price: 100, price_change: 0, cost: 40, cost_source: 'Item Valuation Rate', projected_profit: 400,
      projected_margin: 50, warnings: 'Dealers: below minimum', column_detail: JSON.stringify(columns)}]},
    fields_dict: {results_html: {$wrapper: {html: value => { html = value; }}}},
    is_new: () => false, is_dirty: () => false, save: async () => {}, reload_doc: async () => {},
    add_custom_button: (label, action) => { buttons[label] = action; },
    set_value: (key, value) => { values[key] = value; },
  };

  events.refresh(frm);
  assert.ok(html.includes('Customer Column') && html.includes('Dealers') && html.includes('Traders'));
  assert.ok(html.includes('table-warning'), 'margin below minimum is highlighted');
  assert.equal((html.match(/table-warning/g) || []).length, 1, 'Traders row is not highlighted');
  assert.ok(html.includes('&lt;b&gt;P1&lt;/b&gt;') && !html.includes('<b>P1</b>'), 'item code escaped');
  assert.ok(html.includes('Dealers: below minimum'));
  assert.ok(html.includes('800.00') && html.includes('50.0%'));

  await buttons['Load Items']();
  assert.equal(calls[0].method, 'vortexus_discount_matrix.simulation.load_items');
  assert.equal(JSON.stringify(calls[0].args), JSON.stringify({name: 'VDM-SIM-1'}));
  assert.ok(messages[0].includes('Added 3 items'));
  assert.ok(buttons.Recalculate);

  frm.doc.items[0].column_detail = '{bad';
  events.refresh(frm);
  assert.ok(html.includes('could not be read'));
  frm.doc.items = [];
  events.refresh(frm);
  assert.ok(html.includes('Load Items'));

  const fresh = {doc: {}, is_new: () => true, set_value: (k, v) => { fresh.doc[k] = v; }};
  events.onload(fresh);
  assert.deepEqual(fresh.doc, {to_date: '2026-10-23', from_date: '2025-10-23', company: 'Vortexus'});
  console.log('Price simulation form checks passed: detail table, highlighting, escaping, Load Items and defaults.');
})().catch(error => { console.error(error); process.exitCode = 1; });
