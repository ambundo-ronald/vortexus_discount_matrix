const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
(async () => {
  for (const allowed of [true, false]) {
    const handlers = {}, buttons = {'Approve Discount Exception': () => {}};
    const frappe = {
      utils: {escape_html: s => s}, ui: {form: {on: (dt, events) => {handlers[dt] = events;}}},
      user: {has_role: () => true}, call: async () => ({message: {allow_approval: allowed}}),
    };
    vm.runInNewContext(fs.readFileSync('vortexus_discount_matrix/public/js/transaction.js', 'utf8'), {frappe, __: s => s, console, setTimeout, clearTimeout});
    await handlers['Sales Order'].refresh({doc: {docstatus: 0}, is_new: () => false,
      remove_custom_button: name => {delete buttons[name];},
      add_custom_button: (name, fn) => {buttons[name] = fn;}, dashboard: {set_headline_alert: () => {}}});
    assert.equal(Boolean(buttons['Approve Discount Exception']), allowed);
  }
  console.log('Manager button follows approval setting and removes stale buttons.');
})().catch(error => {console.error(error); process.exitCode = 1;});
