const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let events;
const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
vm.runInNewContext(fs.readFileSync('vortexus_discount_matrix/public/js/approval.js', 'utf8'), {
  frappe: {utils: {escape_html: escape}, ui: {form: {on: (name, handlers) => {events = handlers;}}}}, Intl,
});
function render(raw) {
  let html;
  events.refresh({doc: {snapshot: raw}, fields_dict: {approved_terms_table: {$wrapper: {html: value => {html = value;}}}}});
  return html;
}
const data = {document: 'INV-TEST', customer_group: 'Dealers', matrix_column: 'Dealers', header: {currency: 'KES'},
  items: [{item_code: 'EXCLUDED', qty: 9}, {item_code: '<script>alert(1)</script>', qty: 3, uom: 'Nos'}],
  lines: [{row: 2, item_code: '<script>alert(1)</script>', item_group: 'Filters', reference_price: 500,
    reference_net_rate: 500, max_discount: 30, minimum_net_rate: 350, actual_net_rate: 150, effective_discount: 70}]};
const raw = JSON.stringify(data);
const html = render(raw);
assert.ok(html.includes('<table'));
assert.ok(html.includes('Exception approved'));
assert.ok(html.includes('3.00'));
assert.ok(html.includes('Nos'));
assert.ok(html.includes('&lt;script&gt;'));
assert.ok(!html.includes('<script>'));
assert.equal(JSON.stringify(data), raw);
assert.ok(render('{bad').includes('could not be read'));
assert.ok(render('{}').includes('No matrix item lines'));
data.lines[0].actual_net_rate = 400;
assert.ok(render(JSON.stringify(data)).includes('Within limit'));
const marginHtml = render(JSON.stringify({document: 'SO-1', matrix_mode: 'Margin Matrix', header: {currency: 'KES'},
  items: [{item_code: 'PUMP', qty: 2, uom: 'Nos'}],
  lines: [{row: 1, item_code: 'PUMP', item_group: 'Pumps', cost_rate: 100, cost_source: 'Last Purchase Rate', min_margin: 55, minimum_net_rate: 222.23, actual_net_rate: 200, actual_margin: 50}]}));
assert.ok(marginHtml.includes('Unit Cost') && marginHtml.includes('Actual Margin') && marginHtml.includes('Margin Matrix'));
assert.ok(marginHtml.includes('55%') && marginHtml.includes('50%') && marginHtml.includes('Exception approved'));
assert.ok(!marginHtml.includes('Standard Price'));
assert.ok(marginHtml.includes('Last Purchase Rate'));
console.log('Approval table checks passed: old snapshots, quantities, exceptions, malformed data and HTML escaping.');
