;(() => {
  const method = 'vortexus_discount_matrix.validation.';
  const escape = value => frappe.utils.escape_html(String(value ?? ''));
  const isViolation = status => ['Adjust Price', 'Pending Approval', 'Below Cost', 'Below Margin Floor'].includes(status);
  const isBlocked = status => ['Below Cost', 'Below Margin Floor'].includes(status);
  // Red only when a sale is blocked outright; orange when the salesperson can still fix or get approval.
  const COLORS = {'Below Cost': 'red', 'Below Margin Floor': 'red', 'Adjust Price': 'orange', 'Pending Approval': 'orange',
    'Disabled': 'gray', 'Not Applicable': 'gray', 'Approved Exception': 'blue', 'Inherited Exception': 'blue', 'Within Limit': 'green'};
  const LABELS = {'Below Cost': 'Blocked: below cost', 'Below Margin Floor': 'Blocked: below margin floor',
    'Adjust Price': 'Price needs adjusting', 'Pending Approval': 'Waiting for approval', 'Within Limit': 'Prices OK',
    'Approved Exception': 'Exception approved', 'Inherited Exception': 'Approved on source document',
    'Disabled': 'Discount Matrix off', 'Not Applicable': 'Not checked'};
  const num = value => value == null || value === '' ? '' : Number(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});

  // The lowest net unit price that clears every rule on the line.
  function lowestAllowed(line) {
    const parts = [line.minimum_net_rate, line.margin_floor, line.below_cost ? line.cost_rate : null]
      .filter(v => v != null && v !== '').map(Number);
    return parts.length ? Math.max(...parts) : null;
  }

  function reason(line) {
    if (line.below_cost) return __('Below cost');
    if (line.below_floor) return __('Below {0}% margin floor', [line.min_margin]);
    if (line.min_margin != null && line.cost_rate == null) return __('No cost found');
    if (line.level === 'Sales Manager' && line.max_discount != null) return __('Discount above {0}%', [line.max_discount]);
    if (line.level) return __('Margin below {0}%', [line.min_margin]);
    return '';
  }

  function problemsTable(lines, withFix) {
    if (!lines.length) return '';
    const rows = lines.map(l => {
      const lowest = lowestAllowed(l);
      const fix = withFix && lowest != null && !(l.min_margin != null && l.cost_rate == null)
        ? `<button class="btn btn-xs btn-default vdm-fix" data-row="${escape(l.row)}" data-net="${escape(lowest)}">${__('Use lowest')}</button>` : '';
      return `<tr><td>${escape(l.row)}</td><td>${escape(l.item_code)}</td><td class="text-right">${num(l.actual_net_rate)}</td>`
        + `<td class="text-right"><b>${num(lowest)}</b></td><td>${escape(reason(l))}</td>${withFix ? `<td>${fix}</td>` : ''}</tr>`;
    }).join('');
    return `<table class="table table-sm table-bordered vdm-table" style="margin:8px 0 0;background:var(--card-bg, #fff)">`
      + `<thead><tr><th>${__('Row')}</th><th>${__('Item')}</th><th class="text-right">${__('Your net price')}</th>`
      + `<th class="text-right">${__('Lowest allowed')}</th><th>${__('Issue')}</th>${withFix ? '<th></th>' : ''}</tr></thead><tbody>${rows}</tbody></table>`;
  }

  function excludedNote(result) {
    if (!result.excluded_rows?.length) return '';
    const items = result.excluded_rows.map(r => `${__('Row')} ${escape(r.row)} (${escape(r.item_code)}): ${escape(r.reason)}`).join('<br>');
    return `<details style="margin-top:6px"><summary class="text-muted small">${__('{0} rows not checked', [result.excluded_rows.length])}</summary><div class="small text-muted">${items}</div></details>`;
  }

  function panel(result, withFix) {
    const status = result.status;
    const problems = (result.violations || []).length ? result.violations : (isViolation(status) ? (result.lines || []).filter(l => l.level) : []);
    let html = `<div class="vdm-panel"><span class="indicator-pill ${COLORS[status] || 'gray'}">${escape(LABELS[status] || status)}</span>`
      + ` <span>${escape(result.message)}</span>`;
    if (problems.length) html += problemsTable(problems, withFix);
    if (problems.length && isBlocked(status)) html += `<div class="small text-muted" style="margin-top:4px">${__('Raise the price to at least the lowest allowed.')}</div>`;
    return html + excludedNote(result) + '</div>';
  }

  function highlightRows(frm, problems) {
    const grid = frm.fields_dict?.items?.grid;
    if (!grid?.grid_rows) return;
    const bad = new Set(problems.map(l => Number(l.row)));
    for (const gridRow of grid.grid_rows) {
      const el = gridRow.row || gridRow.wrapper;
      if (el?.toggleClass) el.toggleClass('vdm-problem', bad.has(Number(gridRow.doc?.idx)));
    }
  }

  // Show "Approve Discount Exception" only to a user who can approve these prices: a Finance Manager
  // does not see it on prices only MD can approve, and nobody sees it when nothing needs approval.
  function syncApproveButton(frm, result) {
    if (!frm.remove_custom_button || !frm.add_custom_button) return;
    frm.remove_custom_button(__('Approve Discount Exception'));
    if (!frm._vdm_approver || !result.can_approve || frm.is_new() || frm.doc.docstatus !== 0) return;
    frm.add_custom_button(__('Approve Discount Exception'), () => {
      if (frm.is_dirty()) return frappe.msgprint(__('Save your changes before approving.'));
      frappe.prompt([{fieldname: 'reason', fieldtype: 'Small Text', label: __('Approval reason'), reqd: 1}], async values => {
        await frappe.call({method: method + 'approve', args: {doctype: frm.doc.doctype, name: frm.doc.name, reason: values.reason}, freeze: true});
        await frm.reload_doc();
        await runCheck(frm, false, true);
      }, __('Approve Discount Exception'), __('Approve'));
    });
  }

  function render(frm, result, showDialog) {
    frm._vdm_result = result;
    syncApproveButton(frm, result);
    frm.dashboard.set_headline_alert(panel(result, frm.doc.docstatus === 0), COLORS[result.status] === 'gray' ? 'orange' : (COLORS[result.status] || 'orange'));
    highlightRows(frm, result.violations || []);
    if (showDialog) frappe.msgprint({title: __('Discount Matrix Check'), message: panel(result, false), indicator: COLORS[result.status] || 'orange'});
  }

  // A short toast, only when the outcome changes, instead of a dialog after every save.
  function notifyChange(frm, result) {
    const before = frm._vdm_last_status;
    frm._vdm_last_status = result.status;
    if (before === result.status || !frappe.show_alert) return;
    if (isViolation(result.status)) {
      const count = (result.violations || []).length;
      frappe.show_alert({message: __('{0}: {1} line(s) need attention. See the panel at the top.', [LABELS[result.status], count]), indicator: COLORS[result.status]}, 7);
    } else if (before && isViolation(before) && result.status === 'Within Limit') {
      frappe.show_alert({message: __('All prices are now within the Discount Matrix.'), indicator: 'green'}, 5);
    }
  }

  async function runCheck(frm, showDialog = false, notify = false) {
    const serial = frm._vdm_serial = (frm._vdm_serial || 0) + 1;
    try {
      const response = await frappe.call({
        method: method + 'preview', args: {document: JSON.stringify(frm.doc)}, freeze: showDialog,
        freeze_message: __('Checking discount limits...'),
      });
      if (serial !== frm._vdm_serial) return;
      if (!response.message?.status) throw new Error('Missing matrix result');
      render(frm, response.message, showDialog);
      if (notify) notifyChange(frm, response.message);
      else frm._vdm_last_status = response.message.status;
    } catch (error) {
      frm.dashboard.set_headline_alert(__('Discount Matrix check failed. The prices have not been verified. Check the server error before submitting.'), 'red');
      if (showDialog) frappe.msgprint(__('Discount Matrix check failed. Review the server error or contact your System Manager.'));
      console.error('Discount Matrix check failed', error);
    }
  }

  function schedule(frm) {
    clearTimeout(frm._vdm_timer);
    frm._vdm_serial = (frm._vdm_serial || 0) + 1;
    frm._vdm_timer = setTimeout(() => runCheck(frm, false, true), 600);
  }

  // "Use lowest": set the row rate so its net unit price reaches the lowest allowed.
  // Scaling by rate / net_rate keeps document discounts and tax-inclusive pricing correct.
  async function useLowest(frm, rowIdx, net) {
    const row = (frm.doc.items || []).find(r => Number(r.idx) === Number(rowIdx));
    if (!row || !(row.net_rate > 0) || !(row.rate > 0)) return;
    const target = Math.ceil(net * row.rate / row.net_rate + 0.005);
    await frappe.model.set_value(row.doctype, row.name, 'rate', target);
  }

  if (typeof $ !== 'undefined' && !window.__vdm_bound) {
    window.__vdm_bound = true;
    $('head').append('<style>.vdm-problem, .vdm-problem .static-area{background:var(--bg-orange, #fff5e6)!important}'
      + '.vdm-panel .vdm-table td,.vdm-panel .vdm-table th{padding:3px 8px;font-size:12px;vertical-align:middle}</style>');
    $(document).on('click', '.vdm-fix', function (event) {
      event.preventDefault();
      const frm = window.cur_frm;
      if (frm?.doc && frm.doc.docstatus === 0) useLowest(frm, $(this).data('row'), Number($(this).data('net')));
    });
  }

  for (const dt of ['Quotation', 'Sales Order', 'Sales Invoice']) {
    frappe.ui.form.on(dt, {
      async refresh(frm) {
        frm.add_custom_button(__('Check Discount Matrix'), () => {
          clearTimeout(frm._vdm_timer);
          return runCheck(frm, true);
        });
        frm.remove_custom_button(__('Approve Discount Exception'));
        frm._vdm_approver = false;
        // The server decides who may approve: the Discount Approver Role (Finance Manager) or the margin approver role (MD) set in VDM Settings.
        // The button itself appears only once a check shows this user can approve this document's prices.
        if (!frm.is_new() && frm.doc.docstatus === 0 && !(dt === 'Sales Invoice' && frm.doc.is_return)) {
          let options;
          try {
            options = await frappe.call({method: method + 'approval_options'});
          } catch (error) {
            frm.dashboard.set_headline_alert(__('Discount approval settings could not be loaded. Ask your System Manager to check the site migration. Discount limits remain enforced.'), 'red');
            console.error('Discount approval settings could not be loaded', error);
            return;
          }
          frm._vdm_approver = Boolean(options.message?.allow_approval);
        }
        // Drafts with items: one quiet check fills the panel. No dialog.
        if (frm.doc.docstatus === 0 && (frm.doc.items || []).some(r => r.item_code)) {
          runCheck(frm);
        } else if (frm.doc.docstatus === 1 && frm.doc.custom_vdm_status && COLORS[frm.doc.custom_vdm_status]) {
          frm.dashboard.set_headline_alert(`<span class="indicator-pill ${COLORS[frm.doc.custom_vdm_status]}">${escape(LABELS[frm.doc.custom_vdm_status] || frm.doc.custom_vdm_status)}</span>`,
            COLORS[frm.doc.custom_vdm_status] === 'gray' ? 'orange' : COLORS[frm.doc.custom_vdm_status]);
        }
      },
      after_save(frm) {
        clearTimeout(frm._vdm_timer);
        return runCheck(frm, false, true);
      },
      currency: schedule, conversion_rate: schedule, plc_conversion_rate: schedule,
      transaction_date: schedule, posting_date: schedule,
      quotation_to: schedule, customer: schedule, party_name: schedule, customer_group: schedule, additional_discount_percentage: schedule,
      discount_amount: schedule, apply_discount_on: schedule,
    });
    frappe.ui.form.on(dt + ' Item', {
      item_code: schedule, rate: schedule, discount_percentage: schedule,
      discount_amount: schedule, qty: schedule, uom: schedule,
    });
  }
})();
