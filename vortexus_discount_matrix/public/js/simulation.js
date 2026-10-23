;(() => {
  const method = 'vortexus_discount_matrix.simulation.';
  const esc = value => frappe.utils.escape_html(String(value ?? ''));
  const has = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const money = value => has(value) ? esc(new Intl.NumberFormat(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(value))) : '-';
  const pct = value => has(value) ? esc(Number(value).toFixed(1)) + '%' : '-';
  const qty = value => has(value) ? esc(new Intl.NumberFormat(undefined, {maximumFractionDigits: 3}).format(Number(value))) : '-';

  // [title, key, format] for one customer-group line of an item.
  const GROUP_COLUMNS = [
    ['Customer Group', 'customer_group', esc], ['Matrix Column', 'column', esc], ['Qty Sold', 'qty', qty],
    ['Avg Price Paid', 'history_price', money], ['Past Discount', 'history_discount', pct], ['Max Discount', 'max_discount', pct],
    ['Assumed Discount', 'assumed_discount', pct], ['Expected Price', 'expected_price', money], ['Expected Margin', 'expected_margin', pct],
    ['Projected Revenue', 'projected_revenue', money], ['Projected Profit', 'projected_profit', money],
    ['Price at Max Discount', 'floor_price', money], ['Margin at Max Discount', 'floor_margin', pct], ['Min Margin', 'min_margin', pct],
  ];
  const ITEM_COLUMNS = [
    ['Item', 'item_code', esc], ['Item Name', 'item_name', esc], ['Item Group', 'item_group', esc],
    ['Current Price', 'current_price', money], ['Proposed Price', 'proposed_price', money], ['Price Change', 'price_change', pct],
    ['Cost', 'cost', money], ['Cost Source', 'cost_source', esc],
  ];

  function lines(row) {
    const parsed = JSON.parse(row.column_detail || '[]');
    if (!Array.isArray(parsed)) throw new Error('Invalid detail');
    return parsed.filter(line => line && typeof line === 'object');
  }
  const short = c => has(c.floor_margin) && (has(c.min_margin) ? Number(c.floor_margin) < Number(c.min_margin) : Number(c.floor_margin) < 0);

  function detail(row) {
    let groups;
    try {
      groups = lines(row);
    } catch (_) {
      return '<p class="text-danger">Detail could not be read. Save to recalculate.</p>';
    }
    let html = '<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>'
      + GROUP_COLUMNS.map(([title]) => `<th scope="col">${title}</th>`).join('') + '</tr></thead><tbody>';
    for (const c of groups) {
      html += `<tr${short(c) ? ' class="table-warning"' : ''}>` + GROUP_COLUMNS.map(([, key, format]) => `<td>${format(c[key])}</td>`).join('') + '</tr>';
    }
    return html + '</tbody></table></div>';
  }

  function totalsLine(d) {
    const change = has(d.history_profit) && Number(d.history_profit) !== 0
      ? ` (${pct((Number(d.projected_profit) / Number(d.history_profit) - 1) * 100)} vs history)` : '';
    return `<p><b>Projected revenue</b> ${money(d.projected_revenue)} &nbsp; <b>Projected profit</b> ${money(d.projected_profit)}${change}`
      + ` &nbsp; <b>Projected margin</b> ${pct(d.projected_margin)} &nbsp; <b>Historical revenue</b> ${money(d.history_revenue)}`
      + ` &nbsp; <b>Historical profit</b> ${money(d.history_profit)}</p>`;
  }

  function render(frm) {
    const field = frm.fields_dict.results_html;
    if (!field) return;
    const rows = frm.doc.items || [];
    if (!rows.length) {
      field.$wrapper.html('<p class="text-muted">Select a Load Item Group and save, or use Load Items, to fill the table.</p>');
      return;
    }
    const d = frm.doc;
    let html = totalsLine(d)
      + `<p class="text-muted">Same quantities as the sales history period, by customer group. ${esc(d.projection_basis)} basis. `
      + 'Amounts are per stock UOM in company currency and exclude tax. Historical profit uses current cost. Highlighted rows: the maximum discount breaks the margin minimum or goes below cost. Use Preview for one table of everything.</p>';
    for (const row of rows) {
      const warn = row.warnings ? `<div class="text-warning" style="white-space:pre-wrap">${esc(row.warnings)}</div>` : '';
      html += `<details style="margin-bottom:8px"${row.warnings ? ' open' : ''}><summary><b>${esc(row.item_code)}</b> ${esc(row.item_name)}: `
        + `proposed ${money(row.proposed_price)} (current ${money(row.current_price)}, ${pct(row.price_change)}), cost ${money(row.cost)} `
        + `${row.cost_source ? '(' + esc(row.cost_source) + ')' : ''}, projected profit ${money(row.projected_profit)} at ${pct(row.projected_margin)}</summary>`
        + warn + detail(row) + '</details>';
    }
    field.$wrapper.html(html);
  }

  // One flat row per item and customer group, with the item's values repeated.
  function flatten(doc) {
    const result = [];
    for (const row of doc.items || []) {
      let groups;
      try { groups = lines(row); } catch (_) { groups = []; }
      for (const c of groups.length ? groups : [{}]) result.push({item: row, group: c});
    }
    return result;
  }

  function csv(doc) {
    const quote = value => {
      const text = value === null || value === undefined ? '' : String(value);
      return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    const header = [...ITEM_COLUMNS, ...GROUP_COLUMNS].map(([title]) => title).concat('Warnings');
    const body = flatten(doc).map(({item, group}) => ITEM_COLUMNS.map(([, key]) => item[key])
      .concat(GROUP_COLUMNS.map(([, key]) => group[key]), item.warnings || '').map(quote).join(','));
    return [header.map(quote).join(','), ...body].join('\r\n');
  }

  function preview(frm) {
    const rows = flatten(frm.doc);
    let table = '<div style="max-height:70vh;overflow:auto"><table class="table table-bordered table-sm vdm-preview" style="font-size:12px;white-space:nowrap">'
      + '<thead style="position:sticky;top:0;background:var(--fg-color, #fff);z-index:1"><tr>'
      + [...ITEM_COLUMNS, ...GROUP_COLUMNS].map(([title]) => `<th scope="col">${title}</th>`).join('') + '<th scope="col">Warnings</th></tr></thead><tbody>';
    for (const {item, group} of rows) {
      table += `<tr${short(group) ? ' class="table-warning"' : ''}>`
        + ITEM_COLUMNS.map(([, key, format]) => `<td>${format(item[key])}</td>`).join('')
        + GROUP_COLUMNS.map(([, key, format]) => `<td>${format(group[key])}</td>`).join('')
        + `<td style="white-space:pre-wrap;min-width:240px">${esc(item.warnings)}</td></tr>`;
    }
    table += '</tbody></table></div>';
    const dialog = new frappe.ui.Dialog({
      title: __('Simulation Preview: {0}', [frm.doc.title || frm.doc.name]),
      size: 'extra-large',
      fields: [
        {fieldtype: 'HTML', fieldname: 'summary'},
        {fieldtype: 'Data', fieldname: 'search', label: __('Filter rows'), placeholder: __('Item, customer group, column...')},
        {fieldtype: 'HTML', fieldname: 'table'},
      ],
      primary_action_label: __('Download CSV'),
      primary_action() {
        const blob = new Blob(['﻿' + csv(frm.doc)], {type: 'text/csv;charset=utf-8'});
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `${frm.doc.name}-simulation.csv`;
        link.click();
        URL.revokeObjectURL(link.href);
      },
    });
    dialog.fields_dict.summary.$wrapper.html(totalsLine(frm.doc)
      + `<p class="text-muted">${rows.length} rows: one per item and customer group. ${esc(frm.doc.projection_basis)} basis.</p>`);
    dialog.fields_dict.table.$wrapper.html(table);
    const filter = () => {
      const term = String(dialog.get_value('search') || '').toLowerCase();
      dialog.fields_dict.table.$wrapper.find('tbody tr').each(function () {
        this.style.display = !term || this.textContent.toLowerCase().includes(term) ? '' : 'none';
      });
    };
    dialog.fields_dict.search.$input.on('input', filter);
    dialog.show();
    return dialog;
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
      frm.add_custom_button(__('Preview'), async () => {
        if (frm.is_dirty()) await frm.save();
        if (!(frm.doc.items || []).length) return frappe.msgprint(__('Add items first: select a Load Item Group or use Load Items.'));
        return preview(frm);
      });
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
    item_group(frm) {
      // The server adds the selected group's items when the change is saved.
      if (frm.doc.item_group && frm.doc.company && frm.doc.from_date && frm.doc.to_date && frm.doc.title) {
        frappe.show_alert({message: __('Loading items from {0}...', [frm.doc.item_group]), indicator: 'blue'});
        return frm.save();
      }
    },
  });
})();
