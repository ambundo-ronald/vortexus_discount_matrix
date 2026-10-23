;(() => {
  const method = 'vortexus_discount_matrix.simulation.';
  const esc = value => frappe.utils.escape_html(String(value ?? ''));
  const has = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const money = value => has(value) ? esc(new Intl.NumberFormat(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(value))) : '-';
  const pct = value => has(value) ? esc(Number(value).toFixed(1)) + '%' : '-';
  const qty = value => has(value) ? esc(new Intl.NumberFormat(undefined, {maximumFractionDigits: 3}).format(Number(value))) : '-';

  function detail(row) {
    let columns;
    try {
      columns = JSON.parse(row.column_detail || '[]');
      if (!Array.isArray(columns)) throw new Error('Invalid detail');
    } catch (_) {
      return '<p class="text-danger">Detail could not be read. Save to recalculate.</p>';
    }
    let html = '<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>';
    for (const title of ['Customer Column', 'Qty Sold', 'Avg Price Paid', 'Past Discount', 'Max Discount', 'Assumed Discount',
      'Expected Price', 'Expected Margin', 'Projected Revenue', 'Projected Profit', 'Price at Max Discount', 'Margin at Max Discount', 'Min Margin']) {
      html += `<th scope="col">${title}</th>`;
    }
    html += '</tr></thead><tbody>';
    for (const c of columns) {
      if (!c || typeof c !== 'object') continue;
      const short = has(c.floor_margin) && (has(c.min_margin) ? Number(c.floor_margin) < Number(c.min_margin) : Number(c.floor_margin) < 0);
      html += `<tr${short ? ' class="table-warning"' : ''}>` + [esc(c.column), qty(c.qty), money(c.history_price), pct(c.history_discount),
        pct(c.max_discount), pct(c.assumed_discount), money(c.expected_price), pct(c.expected_margin), money(c.projected_revenue),
        money(c.projected_profit), money(c.floor_price), pct(c.floor_margin), pct(c.min_margin)].map(v => `<td>${v}</td>`).join('') + '</tr>';
    }
    return html + '</tbody></table></div>';
  }

  function render(frm) {
    const field = frm.fields_dict.results_html;
    if (!field) return;
    const rows = frm.doc.items || [];
    if (!rows.length) {
      field.$wrapper.html('<p class="text-muted">Save, then use Load Items or add items to the table.</p>');
      return;
    }
    const d = frm.doc;
    const change = has(d.history_profit) && Number(d.history_profit) !== 0
      ? ` (${pct((Number(d.projected_profit) / Number(d.history_profit) - 1) * 100)} vs history)` : '';
    let html = `<p><b>Projected revenue</b> ${money(d.projected_revenue)} &nbsp; <b>Projected profit</b> ${money(d.projected_profit)}${change}`
      + ` &nbsp; <b>Projected margin</b> ${pct(d.projected_margin)}</p>`
      + `<p class="text-muted">Same quantities as the sales history period, by customer column. ${esc(d.projection_basis)} basis. `
      + 'Amounts are per stock UOM in company currency and exclude tax. Historical profit uses current cost. Highlighted rows: the maximum discount breaks the margin minimum or goes below cost. Save after changing prices to recalculate.</p>';
    for (const row of rows) {
      const warn = row.warnings ? `<div class="text-warning" style="white-space:pre-wrap">${esc(row.warnings)}</div>` : '';
      html += `<details style="margin-bottom:8px"${row.warnings ? ' open' : ''}><summary><b>${esc(row.item_code)}</b> ${esc(row.item_name)}: `
        + `proposed ${money(row.proposed_price)} (current ${money(row.current_price)}, ${pct(row.price_change)}), cost ${money(row.cost)} `
        + `${row.cost_source ? '(' + esc(row.cost_source) + ')' : ''}, projected profit ${money(row.projected_profit)} at ${pct(row.projected_margin)}</summary>`
        + warn + detail(row) + '</details>';
    }
    field.$wrapper.html(html);
  }

  frappe.ui.form.on('VDM Price Simulation', {
    onload(frm) {
      if (!frm.is_new()) return;
      const today = frappe.datetime.get_today();
      if (!frm.doc.to_date) frm.set_value('to_date', today);
      if (!frm.doc.from_date) frm.set_value('from_date', frappe.datetime.add_months(today, -12));
      if (!frm.doc.company) frm.set_value('company', frappe.defaults.get_user_default('Company'));
    },
    refresh(frm) {
      render(frm);
      if (frm.is_new()) return;
      frm.add_custom_button(__('Load Items'), async () => {
        if (frm.is_dirty()) await frm.save();
        const response = await frappe.call({method: method + 'load_items', args: {name: frm.doc.name}, freeze: true,
          freeze_message: __('Loading items, prices, costs and sales history...')});
        const r = response.message || {};
        await frm.reload_doc();
        frappe.msgprint(r.not_added
          ? __('Added {0} items. {1} more were not added: a simulation holds at most {2} items. Use Load Item Group to split it.', [r.added, r.not_added, r.limit])
          : __('Added {0} items.', [r.added]));
      });
      frm.add_custom_button(__('Recalculate'), () => frm.save());
    },
  });
})();
