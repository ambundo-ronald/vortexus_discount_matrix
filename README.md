# Vortexus Discount Matrix â€” ERPNext v16

An installable Frappe app implementing the accepted Discount Matrix policy. It covers Quotation, Sales Order and Sales Invoice. No gross-profit or margin rules are included.

## Policy

- 94 exact Item Group mappings are bundled in `vortexus_discount_matrix/data`. The 11 accepted Customer Group mappings seed an editable table in VDM Settings on first installation or upgrade.
- The other groups, including Intercompany and All Customer Groups, are outside this new control. Existing ERPNext controls still apply.
- No item-level overrides or automatic parent-group inheritance.
- Standard Selling is an independent baseline. Direct price increases and discounts below the ceiling are allowed. This app does not automatically apply the maximum discount.
- Item and document discounts are evaluated using ERPNext's recalculated net item rates and a Standard Selling baseline normalized through the same tax calculation.
- Excessive discounts can be saved as drafts with an instruction to adjust the price; submission requires corrected prices or an explicit Sales Manager exception with a nonblank reason.
- Approval is a separate, read-only audit record, bound to the document and its calculated terms. Native source-row links can carry a verified upstream approval; copying status fields does not carry authorization. Different prices, quantities, customer, taxes, baseline prices or limits require approval for those terms. An existing approval for identical terms on the same document remains valid.
- Browser warnings help salespeople; server checks protect normal saves/submissions through Desk, imports and document APIs. Direct database writes by administrators are outside document hooks.

## Installation on a Frappe Cloud private bench

1. Use a private Git repository named `vortexus_discount_matrix` and grant Frappe Cloud access to it. Use an ERPNext v16-compatible bench and Python version matching that bench.
2. Add the repository as a custom app to the private bench, deploy the updated bench, then install `vortexus_discount_matrix` on a **staging copy** of the site first.
3. Installation creates VDM Settings, VDM Approval and read-only transaction status fields. Enforcement starts **disabled**. Migration does not re-enable or reset it.
4. Open **VDM Settings** through the Desk search bar. Check the accepted mappings and Standard Selling prices, then enable enforcement on staging.
5. Give the authorized manager the existing **Sales Manager** role and write access to the relevant transaction documents. Salespeople retain normal transaction permissions.
6. Complete the acceptance checklist below before installing/enabling on production. Take the normal site backup first.

Equivalent bench commands (run by your deployment administrator):

```sh
bench get-app https://YOUR-REPOSITORY/vortexus_discount_matrix.git
bench --site YOUR-STAGING-SITE install-app vortexus_discount_matrix
bench --site YOUR-STAGING-SITE migrate
bench build --app vortexus_discount_matrix
```

Frappe Cloud manages repository deployment; no local commands in this workspace install anything on the live site.

## Customer Group mapping settings (version 0.2)

Open **VDM Settings** as a System Manager. Under **Customer Group to Matrix Group**, add a row, select an existing ERPNext Customer Group, and select its matrix column: Dealers, Traders, Technicians, NGOs / Parastatals, Corporates, or End Users / Retail. Save.

For example: Traders/Contractors/Consultants ? Traders. Several live groups can share the same matrix column, but a live group cannot appear twice. Blank or invalid mappings are rejected. Removing a mapping puts that group outside this new control; it does not assign a zero discount. Intercompany and All Customer Groups remain unmapped unless an administrator deliberately adds them.

Changes take effect on the next preview, validation or submission without a restart. Approval snapshots include the selected column, so changing a customer's mapping changes its approval terms. Submitted documents are not retroactively modified.

An upgrade adds the table and seeds the 11 accepted mappings once. Later migrations preserve edits and intentionally removed rows, even an empty table. Enforcement remains disabled/enabled as it was. Settings changes are version-tracked.

Deploy version 0.2.0 and run the normal site migration. On staging, verify saving a new mapping changes its ceiling, duplicates fail, deleting a mapping excludes that group, and a second migration preserves these edits.

## Sales and approval flow

Salespeople can edit rates normally. **Check Discount Matrix** previews limits; changes to rates and discounts also trigger a delayed preview. A violating draft is marked **Adjust Price** and cannot be submitted.

The Sales Manager opens the saved draft, selects **Approve Discount Exception**, enters a reason and approves. The document displays **Approved Exception**. The manager or a user with existing submit permissions can then submit it. Managers cannot bypass the reason by submitting directly. The app adds no external notifications or automatic emails.

Use **VDM Approval** to review the recorded reason, approver, time and approved snapshot. No custom Workflow is installed, so existing workflows still operate; staging must verify their interaction with the new buttons and submission check. A submitted quotation approval can flow through its linked Sales Order to Sales Invoice. A submitted Sales Order approval can flow to its linked Sales Invoice.

## Explicit boundaries in version 0.1

- Standard Selling and transaction currencies must match. Cross-currency transactions involving mapped groups stop with an explanatory error.
- Standard Selling must contain a positive, general selling price valid on the document date, for the exact UOM or stock UOM. Item-master UOM conversion is validated. Customer/batch-specific prices do not replace the baseline. Multiple equally current prices are treated as ambiguous. Packing units other than 0 or 1 require review.
- Returns, consolidated invoices, nonpositive quantities and alternative quotation rows involving mapped items are not supported yet and stop for review. Cash/non-trade discounts must be replaced with regular additional discounts.
- A mapped Item Group on a lead quotation requires selection of a Customer; otherwise its discount ceiling cannot be determined.
- Missing/ambiguous baseline prices stop saving until corrected. Excessive discounts with a valid baseline can be saved pending approval.
- Inherited Item Group rules are intentionally absent. Every in-scope match is exact.
- Item Group mappings remain version-controlled CSV files in the app. Customer Group mappings are editable only through VDM Settings by System Managers. Updating review files does not change the installed policy. Item Group changes must be bundled and redeployed; customer mappings use saved site settings. Do not rerun `build_mapping.py` against edited review files because it regenerates the original proposal.
- This release has not been run against a real Frappe/ERPNext site in this workspace. Local tests cover pure calculations and mocked approval guards, not full tax, permissions, workflow, migration or browser integration.

## Required staging acceptance

Use a mapped group such as **Pool Pumps**, Dealers, and a Standard Selling rate of 100,000 (Dealer limit 50%). Test each of Quotation, Sales Order and Sales Invoice:

1. 110,000 and 60,000 save/submit normally. 50,000 is allowed; 49,999 requires approval.
2. Additional invoice discounts that move the effective rate below 50,000 require approval. Test Net Total and Grand Total separately, and tax-inclusive and tax-exclusive documents.
3. Editing the transaction price-list rate, item_group, customer_group or matrix status does not bypass the server check; master records and independent Item Prices govern.
4. Sales Users cannot call the approval endpoint successfully. A Sales Manager without a reason is rejected. A manager with a reason can approve a saved draft; the audit record matches the transaction.
5. Change quantity, customer, tax, rate, reference Item Price or policy after approval. Submission requires an approval matching the changed terms. Create linked Orders/Invoices: verified upstream approvals can authorize matching terms; copied status fields alone cannot.
6. Exercise non-stock-UOM pricing, missing and overlapping prices, free rows, mixed mapped/excluded rows and each unsupported case above. Verify excluded groups remain outside this app's control.
7. Confirm normal document API/import submissions hit the same block and ordinary users cannot create, edit or delete approval records.
8. Check your existing workflows, PDF/email practices for unapproved draft quotations, and the Sales Order update-items-after-submit path. This app blocks submission, not all draft printing/sharing.

## Local checks

```sh
python -m unittest discover -s tests -v
python -m compileall -q vortexus_discount_matrix
node --check vortexus_discount_matrix/public/js/transaction.js
```

Official references used: [Frappe document hooks](https://docs.frappe.io/framework/user/en/python-api/hooks), [Frappe Cloud app installation](https://docs.frappe.io/cloud/installing-an-app), and the [ERPNext version-16 tax controller](https://github.com/frappe/erpnext/blob/version-16/erpnext/controllers/taxes_and_totals.py).


## Repository contents and publishing

Track the app, accepted policy CSVs, tests, README, license and GitHub Actions checks. Raw Excel exports, local review files, downloaded reference sources, credentials and generated packages are ignored. Bundled policy files contain company-specific discount information; keep the remote repository private.

After creating an empty private GitHub repository (without an auto-generated README or license):

```sh
git remote add origin https://github.com/YOUR-ACCOUNT/vortexus_discount_matrix.git
git push -u origin main
```

Connect that repository and the `main` branch to the Frappe Cloud private bench. The CI workflow checks calculations, mocked adapters, syntax and packaging; it does not replace staging tests on ERPNext.


## Installation troubleshooting: unrelated custom fields

If installation reports `Delivery Personnel: Options must be a valid DocType`, the existing Sales Invoice field `custom_delivery_personnel` has missing/invalid Link options. The installer now uses Frappe's scoped `ignore_validate` option only when adding/updating its three display fields per transaction. It leaves all unrelated fields untouched and retains normal discount/approval validation. Re-running installation or migration updates the same fields without creating duplicates.

Deploy the latest main commit on the private bench, then retry installation. If the app already appears installed after a partial failure, run a site migration instead; the after_migrate hook completes setup. The unrelated field still needs its intended DocType configured by its owner; the app does not guess or change that target.

The reported site also has an existing `pricing_rule` app overriding sales document controllers and existing discount-approval hooks. Keep VDM enforcement disabled until staging verifies how both systems interact; installing VDM does not remove the existing approval rules.


## Version 0.2.1: explicit checks and adjust-price messaging

The Check Discount Matrix button always opens a result dialog, including Disabled and Not Applicable outcomes. It lists checked limits and excluded item rows. A violating saved draft shows Adjust Price and tells the salesperson to increase the price or reduce the discount. No approval request, workflow assignment, or notification to a manager is created automatically. A Sales Manager may deliberately open the saved draft and approve an exception with a reason.

Before submission the server checks the current terms independently of displayed status. A second on_submit hook checks the persisted document within the submission transaction; a violation raises an exception to roll back submission. These checks still respect the enable setting and accepted scope: disabled enforcement or unmapped groups do not block sales. The dialog now explains those cases visibly.

The reported 500-to-150 Technician scenario is tested against a mapped Water Treatment Equipment group (36% ceiling; minimum 320) for all three document types using controlled ERPNext tax doubles. Button tests cover all five outcomes. Actual site verification is still required, particularly with the installed pricing_rule overrides. The exact cause of the reported live submission cannot be established without its Item Group, saved settings, and deployed version.


## Version 0.3: carry forward approved discounts

Approve the quotation exception with a reason, submit the quotation, then use ERPNext's normal Create Sales Order flow. A linked order at the approved or higher final net unit prices needs no additional exception approval. Submit the order and create its Sales Invoice: the invoice can inherit through the order to the quotation. An explicitly approved Sales Order also authorizes its downstream invoices.

The check shows **Inherited Exception** and identifies the source document. No new manager reason is requested. Ordinary ERPNext permissions and any other installed app's workflows still apply.

Carry-forward verifies a submitted, noncancelled source with a currently valid VDM approval, the same customer, company and currency, the exact source child-row link and item, the same UOM/conversion, and equal or higher final net unit prices after additional discounts. Partial quantities are allowed; quantities across submitted downstream documents cannot exceed the source row. Duplicate target rows are counted together. Cancelled downstream documents no longer consume quantity; returns do not replenish it automatically. Invalid/missing links, extra discounts, changed items or exceeded quantities require price correction or a new explicit manager approval.

Quotation approvals reach invoices through a Sales Order, using ERPNext's native links. Standalone invoices without sales-order item links do not inherit quotation approval. Existing approvals remain stored on their original document; the source is revalidated each time, and a cancelled or changed source does not provide a blanket exemption.

Staging acceptance: approve and submit a 10-unit quotation at 150 for an item listed at 500; create a linked order at 150, submit it, and invoice 4 then 6 units without new approvals. Confirm an eleventh unit, price 149, another customer, a replaced row link and a cancelled source cannot inherit. Repeat starting with a directly approved order. Verify mixed approved/unapproved lines and your other pricing_rule app's behaviour.


## Version 0.3.1: readable approved terms

VDM Approval displays the saved matrix lines as a read-only table with quantity/UOM, reference prices, discount ceiling, minimum and approved net unit prices, effective discount and exception highlighting. The original JSON remains stored unchanged and is available under View original approval data. Rendering uses historical snapshot values, not current Item Prices. Existing approvals work after migration; no approval records are rewritten.

Deploy main, migrate the site, then refresh the browser. The migration adds an HTML display field and hides the original raw-text control. Test an existing approval with both compliant and exceptional lines; quantities must follow the original row number, including when some source items were outside the matrix.


## Version 0.4: Items Outside Discount Matrix report

After deployment and migration, search Desk for **Items Outside Discount Matrix**. Sales Managers and System Managers with Item read access can run the report. It reads current Item masters and compares their exact groups to the same accepted Item Group policy used by validation. It includes deliberately excluded groups and new/unmapped groups; it does not change their mappings.

Columns: Item Code, Item Name, Item Group, Stock UOM, Sales Item, Disabled and Reason. By default all visible items, including disabled and nonsales items, are considered. Filter by exact Item Group, exclude disabled items, or select Sales Items Only. Summary cards count returned items and unmapped groups. Use the standard report export menu to download results.

This is a group-coverage report, not a list of sales transactions exceeding discounts. It does not treat missing customer-group mappings or disabled enforcement as item-mapping failures. Item permissions apply. Verify report discovery and exports on staging after migration.


## Version 0.4.1: stable approval comparison

Approval comparison now normalizes equivalent numeric representations (for example 1 and 1.0), blank optional values and item-tax JSON formatting. It does not round away price or quantity changes. Old approval records are compared using their saved snapshots without rewriting audit data. Approvals are recorded after the document save/reload, and rejection messages identify changed snapshot paths when a previous approval exists. The actual cause of a specific rejection still requires comparison with that document's saved approval terms.


## Version 0.5: enable or disable manager exceptions

VDM Settings now includes **Allow Sales Manager Discount Exceptions**, editable by System Managers. It starts checked to preserve the current approval behaviour and migrations preserve subsequent changes.

When checked, an unchanged, valid approved document can submit without another approval; eligible source-document approvals can carry forward. Normal ERPNext submit permissions still apply. When unchecked, the manager approval button is removed on form refresh, the approval API rejects requests, and both direct and inherited approval records are ignored for exception enforcement. Sales above the matrix limits must be corrected. Existing approval audit records and submitted documents are not deleted or changed. Re-enabling the setting allows still-valid historical approvals again.

The separate **Enable discount matrix enforcement** switch remains the master control. Turning enforcement off disables this app's price blocks altogether. To enforce strict limits with no exceptions, leave enforcement checked and uncheck only the manager-exceptions setting. Refresh open sales forms after changing settings; server checks take effect immediately.


## Version 0.5.1: visible approval control and app sidebar

The manager-exceptions checkbox now appears directly below enforcement, before customer mappings. Migration preserves the saved setting value and mappings.

The app sidebar links to VDM Settings (including customer mappings), Discount Approvals, Items Outside Discount Matrix, Quotations, Sales Orders, Sales Invoices, Items, Item Groups, Customer Groups, Item Prices and Price Lists. Normal role permissions apply. Migration adds missing links without deleting existing links.

Deploy version 0.5.1 and migrate the site in Frappe Cloud, then reload Desk. If the checkbox is still absent, confirm the deployed app version and successful site migration. Updating the repository alone does not update the live site.


## Version 0.5.2: prevent blank forms when scripts are combined

Both form scripts now begin with a statement separator. Without it, a preceding controller ending in `frappe.ui.form.on(...)` without a semicolon can be interpreted as calling that statement's return value, causing `TypeError: frappe.ui.form.on(...) is not a function` before the form renders. The regression test reproduces that failure and verifies transaction and approval scripts load safely after the same controller.

Deploy this release with updated assets, migrate the site, and hard-refresh the browser. Discount enforcement and approval rules are unchanged.


## Version 0.5.3: explicit settings repair migration

An explicit post-model-sync patch runs the idempotent installer and verifies that the manager-approval field exists. The existing after-migrate hook remains in place. Approval-settings request failures now leave the form usable, hide approval actions and display an administrator-facing migration message; server-side enforcement is unchanged.

Deploy this version and run a successful migration on the affected site. For an administrator with bench access, run `bench --site erp.vortexusindustrial.com migrate`, then reload Desk. If migration fails, inspect the first error in its log; browser cache clearing cannot create a missing DocField. Existing mapping values and an already configured approval switch are preserved.


## Version 0.5.4: quotation customer identity comparison

Customer quotations compare blank or matching transient `customer` aliases using the saved `party_name`. This applies to historical approval snapshots without rewriting them. Conflicting customer aliases, changes to quotation_to/party_name, and changes to prices or other approved terms still invalidate approval. Sales Order and Sales Invoice comparisons are unchanged. Deploy and migrate, then retry the unchanged approved quotation.
