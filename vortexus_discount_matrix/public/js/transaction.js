(() => {
  const method = 'vortexus_discount_matrix.validation.';
  const escape = value => frappe.utils.escape_html(String(value ?? ''));
  const isViolation = status => ['Adjust Price', 'Pending Approval'].includes(status);

  function render(frm, result, showDialog) {
    const colors = {'Adjust Price': 'red', 'Pending Approval': 'red', 'Disabled': 'orange', 'Not Applicable': 'orange', 'Approved Exception': 'blue', 'Inherited Exception': 'blue', 'Within Limit': 'green'};
    const color = colors[result.status] || 'orange';
    let content = `<b>${escape(result.status)}</b><br>${escape(result.message)}`;
    if (result.lines?.length) {
      content += '<br><br>' + result.lines.map(r =>
        `Row ${escape(r.row)} (${escape(r.item_code)}): maximum discount ${escape(r.max_discount)}%; minimum net unit price ${escape(r.minimum_net_rate)}; entered net unit price ${escape(r.actual_net_rate)}.`
      ).join('<br>');
    }
    if (result.excluded_rows?.length) {
      content += '<br><br><b>Rows outside this control</b><br>' + result.excluded_rows.map(r =>
        `Row ${escape(r.row)} (${escape(r.item_code)}), Item Group ${escape(r.item_group)}: ${escape(r.reason)}`
      ).join('<br>');
    }
    frm.dashboard.set_headline_alert(content, color);
    if (showDialog) frappe.msgprint({title: __('Discount Matrix Check'), message: content, indicator: color});
  }

  async function runCheck(frm, showDialog = false, violationsOnly = false) {
    const serial = frm._vdm_serial = (frm._vdm_serial || 0) + 1;
    try {
      const response = await frappe.call({
        method: method + 'preview', args: {document: JSON.stringify(frm.doc)}, freeze: showDialog,
        freeze_message: __('Checking discount limits...'),
      });
      if (serial !== frm._vdm_serial) return;
      if (!response.message?.status) throw new Error('Missing matrix result');
      render(frm, response.message, showDialog || (violationsOnly && isViolation(response.message.status)));
    } catch (error) {
      frm.dashboard.set_headline_alert(__('Discount Matrix check failed. The prices have not been verified. Check the server error before submitting.'), 'red');
      if (showDialog) frappe.msgprint(__('Discount Matrix check failed. Review the server error or contact your System Manager.'));
      console.error('Discount Matrix check failed', error);
    }
  }

  function schedule(frm) {
    clearTimeout(frm._vdm_timer);
    frm._vdm_serial = (frm._vdm_serial || 0) + 1;
    frm._vdm_timer = setTimeout(() => runCheck(frm), 600);
  }
  for (const dt of ['Quotation', 'Sales Order', 'Sales Invoice']) {
    frappe.ui.form.on(dt, {
      refresh(frm) {
        frm.add_custom_button(__('Check Discount Matrix'), () => {
          clearTimeout(frm._vdm_timer);
          return runCheck(frm, true);
        });
        if (!frm.is_new() && frm.doc.docstatus === 0 && frappe.user.has_role('Sales Manager')) {
          frm.add_custom_button(__('Approve Discount Exception'), () => {
            if (frm.is_dirty()) return frappe.msgprint(__('Save your changes before approving.'));
            frappe.prompt([{fieldname: 'reason', fieldtype: 'Small Text', label: __('Approval reason'), reqd: 1}], async values => {
              await frappe.call({method: method + 'approve', args: {doctype: dt, name: frm.doc.name, reason: values.reason}, freeze: true});
              await frm.reload_doc();
              await runCheck(frm, true);
            }, __('Approve Discount Exception'), __('Approve'));
          });
        }
        if (isViolation(frm.doc.custom_vdm_status)) {
          frm.dashboard.set_headline_alert(__('Discount exceeds the permitted limit. Increase the selling price or reduce the discount.'), 'red');
        } else if (frm.doc.custom_vdm_status === 'Disabled') {
          frm.dashboard.set_headline_alert(__('Discount Matrix enforcement is disabled in VDM Settings.'), 'orange');
        }
      },
      after_save(frm) {
        clearTimeout(frm._vdm_timer);
        return runCheck(frm, false, true);
      },
      customer: schedule, party_name: schedule, additional_discount_percentage: schedule,
      discount_amount: schedule, apply_discount_on: schedule,
    });
    frappe.ui.form.on(dt + ' Item', {
      item_code: schedule, rate: schedule, discount_percentage: schedule,
      discount_amount: schedule, qty: schedule, uom: schedule,
    });
  }
})();
