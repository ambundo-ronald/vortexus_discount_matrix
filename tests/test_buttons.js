const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
  for (const status of ['Disabled', 'Not Applicable', 'Within Limit', 'Adjust Price', 'Approved Exception', 'Inherited Exception']) {
    const handlers = {}, buttons = {}, dialogs = [];
    const frappe = {
      utils: {escape_html: value => value},
      ui: {form: {on: (doctype, events) => { handlers[doctype] = events; }}},
      user: {has_role: () => false},
      call: async () => ({message: {status, message: 'Visible result', lines: [], violations: [], excluded_rows: []}}),
      msgprint: message => dialogs.push(message),
    };
    const frm = {
      doc: {doctype: 'Sales Order', docstatus: 0},
      is_new: () => false,
      remove_custom_button: () => {},
      add_custom_button: (label, action) => { buttons[label] = action; },
      dashboard: {set_headline_alert: () => {}},
    };
    vm.runInNewContext(fs.readFileSync('vortexus_discount_matrix/public/js/transaction.js', 'utf8'), {
      frappe, __: value => value, console, setTimeout, clearTimeout,
    });
    await handlers['Sales Order'].refresh(frm);
    await buttons['Check Discount Matrix']();
    assert.equal(dialogs.length, 1, status + ' must produce a visible dialog');
    assert.ok(dialogs[0].message.includes(status));
    assert.equal(buttons['Approve Discount Exception'], undefined);
  }
  console.log('Button checks passed for all six outcomes.');
})().catch(error => {console.error(error); process.exitCode = 1;});
