app_name = "vortexus_discount_matrix"
app_title = "Vortexus Discount Matrix"
app_publisher = "Vortexus Industrial Solutions Limited"
app_description = "Discount matrix limits and auditable manager exceptions"
app_email = ""
app_license = "MIT"
required_apps = ["erpnext"]
after_install = "vortexus_discount_matrix.setup.install"
after_migrate = "vortexus_discount_matrix.setup.install"

doc_events = {
    dt: {
        "validate": "vortexus_discount_matrix.validation.validate",
        "on_submit": "vortexus_discount_matrix.validation.on_submit",
        "before_submit": "vortexus_discount_matrix.validation.before_submit",
        "before_update_after_submit": "vortexus_discount_matrix.validation.before_submit",
    }
    for dt in ("Quotation", "Sales Order", "Sales Invoice")
}
doctype_js = {dt: "public/js/transaction.js" for dt in doc_events}

doc_events['VDM Settings'] = {'validate': 'vortexus_discount_matrix.settings.validate'}
