const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
(async () => {
  // allowed: the user's role may approve at all; canApprove: the check says this user can approve these prices.
  const cases = [
    {allowed: true, canApprove: true, shown: true},
    {allowed: true, canApprove: false, shown: false},   // e.g. Finance Manager on a below-cost line (MD only)
    {allowed: false, canApprove: true, shown: false},
    {allowed: 'request_failed', canApprove: true, shown: false},
    {allowed: 'credit_note', canApprove: true, shown: false},
  ];
  for (const {allowed, canApprove, shown} of cases) {
    const handlers = {}, buttons = {'Approve Discount Exception': () => {}};
    let checked;
    const done = new Promise(resolve => { checked = resolve; });
    const frappe = {
      utils: {escape_html: s => s}, ui: {form: {on: (dt, events) => {handlers[dt] = events;}}},
      user: {has_role: () => true},
      call: async ({method}) => {
        if (method.endsWith('approval_options')) {
          if (allowed === 'request_failed') throw new Error('Field allow_manager_approvals does not exist');
          return {message: {allow_approval: allowed === true}};
        }
        setTimeout(checked, 0);
        return {message: {status: 'Below Cost', message: 'Blocked', lines: [], violations: [{row: 1, level: 'Margin Approver'}], can_approve: canApprove}};
      },
    };
    vm.runInNewContext(fs.readFileSync('vortexus_discount_matrix/public/js/transaction.js', 'utf8'), {frappe, __: s => s, console, setTimeout, clearTimeout});
    const doctype = allowed === 'credit_note' ? 'Sales Invoice' : 'Sales Order';
    const frm = {doc: {doctype, docstatus: 0, is_return: allowed === 'credit_note' ? 1 : 0, items: [{idx: 1, item_code: 'RO'}]},
      is_new: () => false, fields_dict: {},
      remove_custom_button: name => {delete buttons[name];},
      add_custom_button: (name, fn) => {buttons[name] = fn;}, dashboard: {set_headline_alert: () => {}}};
    await handlers[doctype].refresh(frm);
    if (allowed !== 'request_failed') await done;
    assert.equal(Boolean(buttons['Approve Discount Exception']), shown, JSON.stringify({allowed, canApprove}));
    assert.ok(buttons['Check Discount Matrix']);
  }
  console.log('Approve button appears only for users who can approve the current prices.');
})().catch(error => {console.error(error); process.exitCode = 1;});
