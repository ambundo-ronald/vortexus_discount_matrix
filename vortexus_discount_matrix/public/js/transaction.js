(() => {
  const method = 'vortexus_discount_matrix.validation.';
  function render(frm, result) {
    const pending = result.status === 'Pending Approval';
    frm.dashboard.clear_headline();
    if (pending) {
      const lines = result.violations.map(r =>
        `Row ${r.row}: maximum discount ${r.max_discount}%; minimum net unit price ${r.minimum_net_rate}.`
      ).join('<br>');
      frm.dashboard.set_headline_alert(`${lines}<br>Consult the Sales Manager for approval with a reason.`, 'orange');
    }
  }
  function check(frm) {
    clearTimeout(frm._vdm_timer);
    frm._vdm_timer = setTimeout(async () => {
      const serial = frm._vdm_serial = (frm._vdm_serial || 0) + 1;
      const response = await frappe.call({method: method + 'preview', args: {document: JSON.stringify(frm.doc)}});
      if (serial === frm._vdm_serial) render(frm, response.message);
    }, 600);
  }
  for (const dt of ['Quotation', 'Sales Order', 'Sales Invoice']) {
    frappe.ui.form.on(dt, {
      refresh(frm) {
        frm.add_custom_button(__('Check Discount Matrix'), () => check(frm));
        if (!frm.is_new() && frm.doc.docstatus === 0 && frappe.user.has_role('Sales Manager')) {
          frm.add_custom_button(__('Approve Discount Exception'), () => {
            if (frm.is_dirty()) return frappe.msgprint(__('Save your changes before approving.'));
            frappe.prompt([{fieldname: 'reason', fieldtype: 'Small Text', label: __('Approval reason'), reqd: 1}], async values => {
              await frappe.call({method: method + 'approve', args: {doctype: dt, name: frm.doc.name, reason: values.reason}, freeze: true});
              await frm.reload_doc();
            }, __('Approve Discount Exception'), __('Approve'));
          });
        }
        if (frm.doc.custom_vdm_status === 'Pending Approval') {
          frm.dashboard.set_headline_alert(__('Discount exceeds the permitted limit. Consult the Sales Manager.'), 'orange');
        }
      },
      customer: check, party_name: check, additional_discount_percentage: check,
      discount_amount: check, apply_discount_on: check,
    });
    frappe.ui.form.on(dt + ' Item', {
      rate: check, discount_percentage: check, discount_amount: check, qty: check, uom: check,
    });
  }
})();
