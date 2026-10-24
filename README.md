# Vortexus Discount Matrix â€” ERPNext v16

An installable Frappe app implementing the accepted Discount Matrix policy. It covers Quotation, Sales Order and Sales Invoice. Since version 0.9, VDM Settings can enforce either the discount matrix or a minimum-margin matrix (see Version 0.9).

## Policy

- 94 accepted Item Group limits and 11 accepted Customer Group mappings are bundled in `vortexus_discount_matrix/data`. They seed editable tables in VDM Settings once, on first installation or upgrade. After that, VDM Settings is the policy.
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

- Foreign-currency transactions use a server-resolved ERPNext selling exchange rate for the document date to convert Standard Selling reference prices. Missing or invalid rates block the transaction with an explanatory error.
- Standard Selling must contain a positive, general selling price valid on the document date, for the exact UOM or stock UOM. Item-master UOM conversion is validated. Customer/batch-specific prices do not replace the baseline. Multiple equally current prices are treated as ambiguous. Packing units other than 0 or 1 require review.
- Returns, consolidated invoices, nonpositive quantities and alternative quotation rows involving mapped items are not supported yet and stop for review. Cash/non-trade discounts must be replaced with regular additional discounts.
- A mapped Item Group on a lead quotation requires selection of a Customer; otherwise its discount ceiling cannot be determined.
- Missing/ambiguous baseline prices stop saving until corrected. Excessive discounts with a valid baseline can be saved pending approval.
- Inherited Item Group rules are intentionally absent. Every in-scope match is exact.
- Since version 0.8, Item Group limits and Customer Group mappings are both edited in VDM Settings by System Managers. The bundled CSV files only seed new installations; editing them does not change an installed site. Do not rerun `build_mapping.py` against edited review files because it regenerates the original proposal.
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


## Version 0.6: multi-currency transactions

Quotations, Sales Orders and Sales Invoices can use a different currency from Standard Selling. Item Prices remain in the Standard Selling currency. The app multiplies the reference price by ERPNext's server-resolved selling exchange rate from that currency to the document currency, using transaction_date or posting_date, then applies the existing discount ceiling to the resulting net reference price. UOM conversion and additional discounts remain included.

Example: a KES 13,000 reference at KES-to-USD 0.007692307692 converts to approximately USD 100. A 30% ceiling means a USD 70 minimum net price. Transaction conversion_rate and plc_conversion_rate are not the source of the matrix reference conversion.

Set up Currency Exchange for the direction Standard Selling currency -> transaction currency, with For Selling enabled and a date valid under Accounts Settings' stale-rate rules. ERPNext's configured exchange-rate provider may supply a rate when no suitable stored rate exists. Missing, zero, negative or non-finite rates block checking/saving/submitting; a discount exception cannot replace a missing rate. The app does not add inverse-rate or cross-rate inference beyond ERPNext's resolver.

Approvals retain the converted reference price and currency in their snapshots. A changed converted reference price invalidates the previous approval and requires review. Native approval carry-forward still requires the same transaction currency between source and target; switching the target currency requires its own approval when outside limits. Existing same-currency behavior is unchanged.

Deploy and migrate, then refresh. Before live use, verify one foreign-currency quotation/order/invoice with your exchange rates and taxes, a price at the limit, a price below it, manager approval, and a linked order/invoice in the same currency. Tests use controlled adapters; this release has not been exercised on your live site.


## Version 0.7: Lead quotation customer groups

Lead now has an optional Customer Group link (`custom_customer_group`) below the lead name. Select a Customer Group mapped in VDM Settings before quoting matrix-controlled items directly to a Lead. The server reads the saved Lead group, applies the same item-group limits, and supports explicit manager exceptions. A missing group blocks controlled quotations with an instruction to update the Lead; explicitly unmapped groups remain outside enforcement, as with Customers. Lead editing permissions govern who can change this field.

Approvals remain bound to the Lead, group and approved terms. Changing the Lead or its mapped group invalidates the approval. On conversion to a Customer, select the correct Customer Group on the Customer: it is not automatically copied by this release. Sales Orders use the actual Customer group. Lead-addressed quotation approvals do not automatically carry forward to Customer sales orders; an over-limit order needs its own approval. Existing Customer quotation carry-forward is unchanged.

Deploy, migrate and refresh. Test a Lead quotation at the limit and below it, a missing Lead group, manager approval, and a converted Customer order on staging.


## Version 0.7.1: credit notes

Sales Invoices marked Is Return are outside VDM selling-price enforcement, including credit notes generated from Delivery Note returns and standalone credit notes. They show Not Applicable with a credit-note explanation and do not require Standard Selling prices or matrix exception approval. ERPNext's own return validation, permissions and accounting checks remain unchanged. The approval button is hidden for credit notes.

Normal invoices, quotations and orders retain discount enforcement. A negative quantity alone does not create an exemption. Returns do not replenish inherited approval quantity allowances. Consolidated normal sales remain unsupported. Deploy, migrate and refresh, then verify the Delivery Note Issue Credit Note flow on the site; local tests do not run a full ERPNext return workflow.


## Version 0.8: editable discount matrix

VDM Settings now contains the whole discount matrix in one editable table: **Discount Matrix (maximum discount % from Standard Selling)**. Each row is one exact Item Group, with a maximum discount percentage for each matrix column (Dealers, Traders, Technicians, NGOs / Parastatals, Corporates, End Users / Retail). Solution Line and Category are kept as reference fields in each row's detail.

System Managers can change percentages, add a row for a new Item Group, or delete a row. A deleted row puts that Item Group outside this control; it does not mean zero discount. Enter 0 to allow no discount. Each value must be between 0 and 100, and an Item Group may appear only once. Use the grid's Download and Upload buttons to edit the table in a spreadsheet. Settings changes are version-tracked.

Upgrade: deploy and migrate. The first migration copies the 94 bundled limits into the table once; Item Groups missing on the site are skipped and listed in the migration log. Later migrations preserve edits and deleted rows, including an empty table. Existing percentages do not change until someone edits them.

Changes apply to the next check, save or submission. Approval snapshots record each line's maximum discount, so changing a percentage that affects an approved draft requires a new approval if the document still exceeds the new limit. Carry-forward re-checks the source document under current limits. Submitted documents are not changed. The Items Outside Discount Matrix report uses the same table.

Staging: change one Item Group's Dealers percentage and confirm the check shows the new floor; enter 101 or a duplicate Item Group and confirm saving fails; delete a row and confirm its items show as outside the control; run a second migration and confirm the edits remain.


## Version 0.9: margin matrix and matrix selection

VDM Settings has a new **Matrix In Use** setting with two choices:

- **Discount Matrix** (default; existing behaviour): each percentage is the maximum discount from the Standard Selling price.
- **Margin Matrix**: each percentage is the minimum gross margin the system accepts, calculated as (net selling price - cost) / net selling price.

Only the selected table is enforced. Upgrading keeps Discount Matrix selected, so nothing changes until a System Manager switches it.

The **Margin Matrix** table has the same layout as the discount table: one row per exact Item Group and one percentage for each matrix column (Dealers, Traders, Technicians, NGOs / Parastatals, Corporates, End Users / Retail). On upgrade it is created once with the discount table's Item Groups and every percentage at 0, so only the percentages need entering. Download/Upload is available for spreadsheet editing. Each value must be at least 0 and below 100. With Margin Matrix in use, Item Groups not listed are outside this control, and 0 blocks only sales below cost.

Cost is taken from the first positive value of: the item's valuation rate in the row's warehouse (Bin), the Item master valuation rate, then the Item's last purchase rate. All three are per stock UOM in company currency. The source used is recorded on each checked line and shown on approvals. Cost is converted to the row UOM using the Item master UOM conversion and from company currency to the document currency using the same server-resolved selling exchange rate as the discount check. The selling price is ERPNext's net unit rate, which excludes tax and includes item and additional document discounts. Minimum price = cost / (1 - margin / 100), rounded up. Example: cost 100 and a 55% Dealer margin gives a minimum net price of 222.23; selling at 200 is a 50% margin and needs price correction or a manager exception.

An item with no positive valuation rate or last purchase rate cannot be checked and stops saving with an explanation; receive or purchase stock, or set the Item valuation rate. The last purchase rate is the most recent purchase price and can differ from the stock valuation. A free (zero-price) controlled row is below any margin. Standard Selling prices are not needed in margin mode.

Salespeople see the minimum net price in the check dialog. Together with the margin percentage, this lets them work out the item cost. Consider this before enabling Margin Matrix.

Manager exceptions, carry-forward and the submission checks work the same way in both modes. A margin approval records the cost, the minimum margin and the matrix in use. A change of cost (valuation rate), margin percentage or matrix requires a new approval for a document that is still below the limit. Valuation rates move with stock receipts, so approve margin exceptions close to submission. Carry-forward re-checks the source document under the current matrix and cost. Discount-matrix approvals made before this version remain valid.

The Items Outside Discount Matrix report lists items whose Item Group is missing from the matrix currently in use.

Staging: select Margin Matrix; set one Item Group's Dealers margin to 55%; with a valuation rate of 100, confirm 222.23 passes and 222.22 shows Adjust Price for Quotation, Sales Order and Sales Invoice; confirm an item with only a last purchase rate uses it, and an item with neither is reported; test a foreign-currency document and a non-stock UOM; approve an exception, then change the valuation rate and confirm a new approval is required; switch back to Discount Matrix and confirm the original limits apply.


## Version 0.10: price simulation

Search Desk for **VDM Price Simulation** (also in the app sidebar as Price Simulations). Sales Managers and System Managers can create, edit and delete simulations. Each simulation is a saved scenario, so you can keep several and compare them.

A simulation only reads system data. It does not change Item Prices, the matrix tables or any sales document. To use a price you settle on, update the Standard Selling Item Price as usual.

1. Create a simulation: enter a title, the Company and the sales history period (default: the last 12 months). Optionally choose one Item Group and a Cost Warehouse. Save.
2. Click **Load Items**. It adds enabled sales items in the discount-matrix Item Groups (or only the chosen group). By default it adds only items sold in the period. A simulation holds up to 500 items; use one Item Group per simulation for larger ranges. Items can also be added manually.
3. **Proposed Price** starts at the current Standard Selling price. Change any proposed prices, then save or click **Recalculate**. Saving reloads current prices, costs and sales history; proposed prices are kept.

For each item the simulation shows the current price, proposed price, change, cost and cost source, quantity sold, projected revenue, projected profit, projected margin and the lowest margin the discount matrix allows. Totals are at the top of Results. **Detail by Customer Column** breaks each item down by matrix column (Dealers, Traders, Technicians, NGOs / Parastatals, Corporates, End Users / Retail, plus unmapped customer groups): quantity bought, average price paid, past discount, maximum discount, assumed discount, expected price and margin, projected revenue and profit, the price at the maximum discount, its margin, and the Margin Matrix minimum. Rows where the maximum discount goes below cost or below the Margin Matrix minimum are highlighted and listed as warnings.

How it is calculated:

- **Sales history**: submitted, non-return Sales Invoices for the Company in the period, grouped by item and the invoice's Customer Group, mapped to matrix columns through VDM Settings. Quantities are in stock UOM; amounts are net of discounts, exclude tax, and are in company currency.
- **Past discount** for a column = 1 - net sales / (invoice list price x quantity), using lines sold from a list price. It measures how far below the list price each customer type usually buys.
- **Projection basis**: *Historical discount* assumes each column keeps its past discount on the proposed price, capped at the matrix maximum (larger discounts would be blocked); columns with no list-price history use the matrix maximum. *Maximum matrix discount* assumes every sale is at the highest discount allowed (worst case).
- **Volume**: projected quantities equal the quantities sold in the history period. The simulation does not predict how demand changes with price; judge that yourself, or shorten or lengthen the period.
- **Cost**: the same order as the Margin Matrix: Cost Warehouse valuation rate, Item valuation rate, then last purchase rate. Historical profit is recalculated at today's cost, not the cost at the time of sale.
- **Margin** = (price - cost) / price. The discount matrix and Margin Matrix are both read from VDM Settings, whichever is in use for enforcement.
- Proposed and current prices are per stock UOM in company currency (Standard Selling is converted if its currency differs). If your Standard Selling prices include tax, projected revenue and margins are overstated by the tax.

Items without a Standard Selling price or cost are kept with a warning instead of blocking the save.

Deploy, migrate and reload Desk. On staging, compare one item's projected figures with its actual invoices for the period, change a proposed price and confirm the projection changes, and check an item with no cost and one with no price.


## Version 0.10.1: simulation fixes, preview and customer groups

**Form scripts now load for VDM doctypes.** Frappe does not load `doctype_js` hooks for custom DocTypes, so the Price Simulation buttons (and the VDM Approval terms table from 0.3.1) did not appear. Both scripts are now loaded with Desk through `app_include_js`. After deploying, run the normal migration and asset build, then hard-refresh the browser.

**Selecting an Item Group fills the table.** Choosing a Load Item Group saves the simulation and adds that group's enabled sales items. Existing rows and proposed prices are kept, so you can build a simulation from several groups. With Load Only Items Sold in Period ticked, only items sold in the period are added; a message explains when nothing is found.

**Preview.** The Preview button opens one large table with a row for every item and customer group: item, prices, cost and cost source, then that group's history, assumed discount, expected price and margin, projected revenue and profit, the price and margin at the maximum discount, the margin minimum, and warnings. Type in Filter rows to narrow it, and use Download CSV to open it in a spreadsheet.

**Simulation by customer group.** Each item is simulated for every Customer Group mapped in VDM Settings, plus any unmapped Customer Group with sales in the period. Each group uses its own buying history (quantity and past discount) and its matrix column's limits, so groups that share a column, such as several dealer groups, are shown separately. Below-cost and margin-minimum warnings are listed once per matrix column.


## Version 0.10.2: simulation discounts measured against today's price

**Past discount now uses today's Standard Selling price.** Before, a customer group's past discount was measured against the list price printed on its old invoices and then applied to the proposed price. When a list price had since been raised, the simulation assumed customers would pay proportionally more; when an invoice line was in a different UOM, the discount could come out absurd (for example -772%). Past discount is now 1 - average net price paid per stock UOM / current Standard Selling price per stock UOM. Items with no current price fall back to the invoice list prices.

**Discounts are kept between 0 and 100%.** A group that bought above the list price is assumed to pay the list price, never more.

**New projection basis: Keep price paid.** Each customer group keeps paying its past average price, but never above the proposed price (nobody pays more than the list) and never below the deepest discount the matrix allows (VDM would block it). Groups with no sales history use the matrix maximum. Use this basis to test lowering list prices while keeping net prices the same.

Upgrade: deploy and migrate. Migration adds the new basis to existing sites' Price Simulation form. Open each simulation and save to recalculate. Staging: on an item whose list price was raised this year, confirm Historical no longer projects customers paying more than they did unless the matrix cap forces it; set a proposed price 10% below current with Keep price paid and confirm projected revenue stays close to history.
