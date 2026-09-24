const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

for (const script of ['transaction', 'approval']) {
  const source = fs.readFileSync(`vortexus_discount_matrix/public/js/${script}.js`, 'utf8');
  const registrations = [];
  const frappe = {
    ui: {form: {on: (doctype, events) => { registrations.push(doctype); }}},
  };
  // Frappe combines controller and hook scripts. A preceding controller need
  // not end in a semicolon; form.on returns undefined, not a callable value.
  const preceding = 'frappe.ui.form.on("Existing Controller", {})\n';
  const context = {frappe, __: value => value, console, setTimeout, clearTimeout};
  assert.throws(() => vm.runInNewContext(preceding + source.replace(/^;/, ''), context),
    /is not a function/, 'reproduce the reported error before the fix');
  registrations.length = 0;
  vm.runInNewContext(preceding + source, context);
  const expected = script === 'transaction'
    ? ['Quotation', 'Sales Order', 'Sales Invoice'] : ['VDM Approval'];
  for (const doctype of expected) assert.ok(registrations.includes(doctype), doctype);
}
console.log('Combined form scripts load after a controller without a trailing semicolon.');
