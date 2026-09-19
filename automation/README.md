# WORKFLOW_003 — Enterprise-style Expense Automation Prototype v2

The Dataset-B logs show a repeated `expense_calc` Excel workflow with Microsoft Excel and the financial-accounting system. The logs do **not** expose the production accounting formula or API, so this prototype automates the defensible part: validation, multi-parameter calculation, exception detection, analytics, review package generation, human approval, and an idempotent mock submission.

## Run one file

```powershell
python src\workflow003_automation.py process `
  --input demo\input\enterprise_expenses_10000.xlsx `
  --rules rules.json `
  --output-dir outputs\automation\workflow003
```

## Run all input files in a folder

```powershell
python src\workflow003_automation.py process `
  --input-dir demo\input `
  --rules rules.json `
  --output-dir outputs\automation\workflow003
```

Every supported `.xlsx`, `.xlsm`, and `.csv` file is processed independently. For Excel workbooks, all worksheets containing the required headers are combined into one batch.

## Calculations

- `subtotal_amount = quantity * unit_amount`
- `discount_amount = subtotal_amount * discount_rate`
- `taxable_amount = subtotal_amount - discount_amount`
- `tax_amount = taxable_amount * tax_rate`
- `calculated_amount = taxable_amount + tax_amount`
- `reporting_calculated_amount = calculated_amount * fx_rate_to_reporting`

The output workbook documents the rules in `Calculation_Rules` and contains calculated **values**, not a fragile dependency on Excel recalculation.

## Enterprise-style metrics

The workbook computes total spend, tax, discounts, reimbursable/non-reimbursable spend, average/median/min/max transaction values, unique employees/departments/projects/merchants, spend by employee/department/category/project/merchant/payment method/currency/month, receipt coverage, duplicate detection, potential duplicate patterns, amount-limit exceptions, and missing-receipt exceptions.

## Output

For each input file:

```text
<output-dir>/<input-stem>/<batch-id>/
    processed_<input-stem>.xlsx
    calculated.csv
    exceptions.csv
    summary.json
    state.json
    audit.jsonl
```

Excel sheets include `Summary`, `Calculated_Data`, `Exceptions`, grouping analytics, and `Calculation_Rules`.

## Controls

`BLOCKED` batches cannot be approved. Approval is explicit. `submit` is a deterministic **MOCK** and is idempotent: rerunning it returns the same transaction ID and does not create another transaction.

## Production boundary

Before production, the demonstration policy/limits must be replaced by approved accounting rules; the FX rate must come from an authoritative source; and a real connector, authentication/authorization, reconciliation, rollback, monitoring and governance controls must be added. The prototype intentionally does not invent those details from the logs.

## Demo stress set

The package includes four input files under `demo/input/`:

- `enterprise_expenses_10000.xlsx` — 10,000-row single-sheet clean dataset.
- `enterprise_expenses_multi_sheet_10000.xlsx` — 10,000 rows split across multiple worksheets.
- `enterprise_expenses_anomalies_10000.xlsx` — 10,000-row dataset with deliberate validation problems.
- `enterprise_expenses_5000.csv` — CSV compatibility check.

The batch run was executed against all four files. The three clean inputs completed with 0 errors and 0 warnings. The anomaly file was correctly blocked with 14 errors and 5 warnings. Processing all 35,000 rows and generating the output workbooks completed in about 19 seconds in the test environment.
