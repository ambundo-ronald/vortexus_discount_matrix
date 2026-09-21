# Vortexus Discount Matrix â€” ERPNext v16

An installable Frappe app implementing the accepted Discount Matrix policy. It covers Quotation, Sales Order and Sales Invoice. No gross-profit or margin rules are included.

## Policy

- 94 exact Item Group mappings are bundled in `vortexus_discount_matrix/data`. The 11 accepted Customer Group mappings seed an editable table in VDM Settings on first installation or upgrade.
- The other groups, including Intercompany and All Customer Groups, are outside this new control. Existing ERPNext controls still apply.
- No item-level overrides or automatic parent-group inheritance.
- Standard Selling is an independent baseline. Direct price increases and discounts below the ceiling are allowed. This app does not automatically apply the maximum discount.
- Item and document discounts are evaluated using ERPNext's recalculated net item rates and a Standard Selling baseline normalized through the same tax calculation.
- Excessive discounts can be saved as drafts, but submission requires a Sales Manager exception with a nonblank reason.
- Approval is a separate, read-only audit record, bound to the document and its calculated terms. Copying documents does not carry authorization. Different prices, quantities, customer, taxes, baseline prices or limits require approval for those terms. An existing approval for identical terms on the same document remains valid.
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

Salespeople can edit rates normally. **Check Discount Matrix** previews limits; changes to rates and discounts also trigger a delayed preview. A violating draft is marked **Pending Approval** and cannot be submitted.

The Sales Manager opens the saved draft, selects **Approve Discount Exception**, enters a reason and approves. The document displays **Approved Exception**. The manager or a user with existing submit permissions can then submit it. Managers cannot bypass the reason by submitting directly. The app adds no external notifications or automatic emails.

Use **VDM Approval** to review the recorded reason, approver, time and approved snapshot. No custom Workflow is installed, so existing workflows still operate; staging must verify their interaction with the new buttons and submission check. Quotation, Order and Invoice each require their own exception approval.

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
5. Change quantity, customer, tax, rate, reference Item Price or policy after approval. Submission requires an approval matching the changed terms. Copy to a new Order/Invoice: copied fields cannot authorize it.
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
