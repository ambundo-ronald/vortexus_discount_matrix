;(() => {
  const esc = value => frappe.utils.escape_html(String(value ?? ''));
  function number(value, percent = false) {
    if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '?';
    return esc(new Intl.NumberFormat(undefined, {minimumFractionDigits: percent ? 0 : 2, maximumFractionDigits: percent ? 4 : 6}).format(Number(value))) + (percent ? '%' : '');
  }
  function render(raw) {
    let data;
    try {
      data = JSON.parse(raw || '{}');
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid snapshot');
    } catch (_) {
      return '<p class="text-danger">The saved approval snapshot could not be read. Contact your System Manager.</p>';
    }
    const lines = Array.isArray(data.lines) ? data.lines : [];
    const items = Array.isArray(data.items) ? data.items : [];
    const header = data.header || {};
    const margin = data.matrix_mode === 'Margin Matrix';
    const both = data.matrix_mode === 'Discount and Margin';
    let html = `<h4>Approved Terms</h4><p><b>Document:</b> ${esc(data.document)} &nbsp; <b>Customer group:</b> ${esc(data.customer_group)} &nbsp; <b>Matrix group:</b> ${esc(data.matrix_column)} &nbsp; <b>Matrix:</b> ${both ? 'Discount and Margin' : (margin ? 'Margin Matrix' : 'Discount Matrix')} &nbsp; <b>Currency:</b> ${esc(header.currency)}</p>`;
    if (!lines.length) {
      html += '<p class="text-muted">No matrix item lines are recorded in this approval.</p>';
    } else {
      html += '<p class="text-muted">Prices and quantities are the values saved when approved. This table shows the item lines checked against the matrix. Net prices exclude tax.</p>';
      html += '<div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr>';
      const titles = both
        ? ['Row', 'Item', 'Item Group', 'Qty', 'UOM', 'Standard Price', 'Maximum Discount', 'Discount Floor', 'Unit Cost', 'Cost Source', 'Minimum Margin', 'Margin Floor', 'Approved Net Price', 'Effective Discount', 'Actual Margin', 'Matrix Result']
        : margin
        ? ['Row', 'Item', 'Item Group', 'Qty', 'UOM', 'Unit Cost', 'Cost Source', 'Minimum Margin', 'Minimum Net Price', 'Approved Net Price', 'Actual Margin', 'Matrix Result']
        : ['Row', 'Item', 'Item Group', 'Qty', 'UOM', 'Standard Price', 'Reference Net Price', 'Maximum Discount', 'Minimum Net Price', 'Approved Net Price', 'Effective Discount', 'Matrix Result'];
      for (const title of titles) html += `<th scope="col">${title}</th>`;
      html += '</tr></thead><tbody>';
      for (const line of lines) {
        if (!line || typeof line !== 'object') continue;
        const index = Number(line.row) - 1;
        const candidate = Number.isInteger(index) && index >= 0 ? items[index] : null;
        const item = candidate && candidate.item_code === line.item_code ? candidate : {};
        const floor = both ? Math.max(Number(line.minimum_net_rate ?? -Infinity), Number(line.margin_floor ?? -Infinity)) : line.minimum_net_rate;
        const known = line.actual_net_rate != null && floor != null && Number.isFinite(Number(floor));
        const exceeds = (known && Number(line.actual_net_rate) < Number(floor)) || (both && line.min_margin != null && line.cost_rate == null);
        const result = known ? (exceeds ? 'Exception approved' : 'Within limit') : 'Not recorded';
        html += `<tr${exceeds ? ' class="table-warning"' : ''}>`;
        const cells = both
          ? [esc(line.row), esc(line.item_code), esc(line.item_group), number(item.qty), esc(item.uom), number(line.reference_price), number(line.max_discount, true), number(line.minimum_net_rate), number(line.cost_rate), esc(line.cost_source || 'Not recorded'), number(line.min_margin, true), number(line.margin_floor), number(line.actual_net_rate), number(line.effective_discount, true), number(line.actual_margin, true), result]
          : margin
          ? [esc(line.row), esc(line.item_code), esc(line.item_group), number(item.qty), esc(item.uom), number(line.cost_rate), esc(line.cost_source || 'Not recorded'), number(line.min_margin, true), number(line.minimum_net_rate), number(line.actual_net_rate), number(line.actual_margin, true), result]
          : [esc(line.row), esc(line.item_code), esc(line.item_group), number(item.qty), esc(item.uom), number(line.reference_price), number(line.reference_net_rate), number(line.max_discount, true), number(line.minimum_net_rate), number(line.actual_net_rate), number(line.effective_discount, true), result];
        for (const cell of cells) html += `<td>${cell}</td>`;
        html += '</tr>';
      }
      html += '</tbody></table></div>';
    }
    html += `<details style="margin-top:16px"><summary>View original approval data</summary><pre style="white-space:pre-wrap;margin-top:8px">${esc(JSON.stringify(data, null, 2))}</pre></details>`;
    return html;
  }
  frappe.ui.form.on('VDM Approval', {
    refresh(frm) {
      const field = frm.fields_dict.approved_terms_table;
      if (field) field.$wrapper.html(render(frm.doc.snapshot));
    },
  });
})();
