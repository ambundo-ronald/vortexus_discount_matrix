const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
  const handlers = {}, dialogs = [], alerts = [], headlines = [], sets = [];
  let reply;
  const frappe = {
    utils: {escape_html: s => String(s).replace(/</g, '&lt;')},
    ui: {form: {on: (dt, events) => { handlers[dt] = events; }}},
    call: async ({method}) => method.endsWith('approval_options') ? {message: {allow_approval: false}} : {message: reply},
    msgprint: m => dialogs.push(m), show_alert: (m, s) => alerts.push(m),
    model: {set_value: async (...args) => sets.push(args)},
  };
  vm.runInNewContext(fs.readFileSync('vortexus_discount_matrix/public/js/transaction.js', 'utf8'),
    {frappe, __: (s, a) => a ? s.replace(/\{(\d)\}/g, (_, i) => a[i]) : s, console, setTimeout, clearTimeout});
  const frm = {doc: {doctype: 'Quotation', docstatus: 0, items: []}, is_new: () => false,
    remove_custom_button: () => {}, add_custom_button: () => {}, dashboard: {set_headline_alert: (h, c) => headlines.push([h, c])}};
  const ok = {row: 1, item_code: 'OK-ITEM', actual_net_rate: 500, minimum_net_rate: 350, max_discount: 30, level: null};
  const bad = {row: 2, item_code: '<b>RO</b>', actual_net_rate: 150, minimum_net_rate: 320, max_discount: 30, level: 'Sales Manager'};

  // A violation after save: no dialog, one toast, a panel listing only the problem row with a fix button.
  reply = {status: 'Adjust Price', message: 'Discount exceeds the permitted limit.', lines: [ok, bad], violations: [bad], excluded_rows: []};
  await handlers.Quotation.after_save(frm);
  assert.equal(dialogs.length, 0, 'no dialog after save');
  assert.equal(alerts.length, 1, 'one toast when the status changes');
  const [html, color] = headlines.at(-1);
  assert.equal(color, 'orange', 'fixable problems are orange, not red');
  assert.ok(html.includes('&lt;b>RO') && !html.includes('OK-ITEM'), 'only problem rows are listed, escaped');
  assert.ok(html.includes('vdm-fix') && html.includes('data-net="320"'), 'fix button carries the lowest allowed price');

  // Saving again with the same outcome stays quiet.
  await handlers.Quotation.after_save(frm);
  assert.equal(alerts.length, 1, 'no repeat toast for the same status');

  // Blocked prices are red.
  reply = {status: 'Below Cost', message: 'A price is below cost.', lines: [bad], violations: [{...bad, below_cost: true, cost_rate: 400, level: 'Below Cost'}], excluded_rows: []};
  await handlers.Quotation.after_save(frm);
  assert.equal(headlines.at(-1)[1], 'red');
  assert.ok(headlines.at(-1)[0].includes('data-net="400"'), 'lowest allowed covers cost');

  // Fixed: green toast and a short OK panel.
  reply = {status: 'Within Limit', message: 'All 2 checked item lines are within their limits.', lines: [ok], violations: [], excluded_rows: []};
  await handlers.Quotation.after_save(frm);
  assert.equal(alerts.at(-1).indicator, 'green');
  assert.ok(!headlines.at(-1)[0].includes('<table'));

  // The manual check still opens one dialog.
  await handlers.Quotation.refresh(frm);
  console.log('Panel checks passed: problem rows only, colours, fix button, toasts only on change.');
})().catch(error => { console.error(error); process.exitCode = 1; });
