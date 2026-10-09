  Operation Log Automation

The project takes low-level desktop operation logs, converts them into meaningful activities, segments those activities into work executions, discovers recurring workflow types, analyses the business meaning of those workflows, and prototypes automation for selected processes.

## Project overview

The input consists of desktop-operation logs generated while people perform work on their computers. A raw event is a low-level recorded operation such as a click, keystroke, application switch, clipboard action, browser event, or shortcut. The main challenge is to recover meaningful work from those low-level events.

The project separates this into four concepts:

```text
Event
  |
  v
Activity
  |
  v
Work segment / execution
  |
  v
Workflow type / process
```

A **segment** is the contiguous interval of time in which some execution of a particular process started and finished. A **workflow type** is the recurring kind of work represented by similar segments. The system is therefore not simply a time-gap splitter: it first creates a stable activity representation, detects boundaries between consecutive activities, discovers recurring workflow types, and then analyses those workflows at the business-process level.

The work is organized into three main stages:

1. **Task 1 - Workflow discovery:** recover contiguous work segments from raw desktop-operation logs and group similar segments into workflow types.
2. **Task 2 - Workflow analysis:** examine the discovered workflows using repeated application, document, text, entity, and execution evidence and assign cautious business interpretations.
3. **Task 3 - Automation prototypes:** build working prototypes for selected workflows, with validation and human approval controls rather than direct uncontrolled actions.

The high-level flow is:

```text
Raw operation logs
       |
       v
Activity extraction
       |
       v
Work segmentation
       |
       v
Workflow discovery
       |
       v
Workflow and business analysis
       |
       +----------------------+
       |                      |
       v                      v
Automation prototype 1   Automation prototype 2
```

The repository also contains the development work log, reports, tests, and final output files.

## Datasets

### Dataset A

Dataset A is labelled and was used for development and evaluation.

- About 63 sessions
- About 162,000 raw events
- Ground truth available

Dataset A was used to validate activity extraction, train and evaluate segmentation, compare workflow representations, select the final workflow-discovery approach, and freeze the pipeline before applying it to Dataset B.

### Dataset B

Dataset B is the final unlabeled dataset.

- 15 sessions
- About 20,000 raw events
- No ground truth

The workflow types for Dataset B were discovered from the data itself. Labels from Dataset A were not copied into Dataset B.

## Final Task 1 pipeline

The main Task 1 execution path is:

```text
src/activities.py
        |
        v
src/case_segment_ml_v6.py
        |
        v
src/process_discovery_final.py
        |
        v
src/finalize_segments.py
        |
        v
outputs/segments.jsonl
```

### Activity extraction

`src/activities.py` converts raw events into atomic activities such as:

- `APP_SWITCH`
- `CLICK`
- `COPY`
- `SHORTCUT`
- `SCROLL`
- `TEXT_ENTRY`
- `OTHER`

This gives the later stages a stable representation without treating every low-level event as a separate unit.

The activity extractor was validated on Dataset A before being frozen. In a representative session, 2,348 raw events were reduced to 388 activities. A text-reconstruction check also confirmed that the extractor correctly matched the expected keyboard-derived text in all 96 tested cases.

### Segmentation

`src/case_segment_ml_v6.py` predicts whether a boundary exists between two consecutive activities.

The final model is logistic regression with a session-level train/validation/test split:

- 40 training sessions
- 10 validation sessions
- 13 held-out evaluation sessions

Final settings:

| Setting | Value |
|---|---:|
| Boundary threshold | 0.65 |
| Minimum segment duration | 12 s |
| Boundary mode | Previous activity end |

Held-out transition results:

| Metric | Result |
|---|---:|
| Precision | 0.9788 |
| Recall | 0.9105 |
| F1 | 0.9434 |
| ROC-AUC | 0.9307 |
| PR-AUC | 0.9864 |

Boundary F1 with different timing tolerances:

| Tolerance | F1 |
|---|---:|
| ±0.5 s | 0.4503 |
| ±1 s | 0.4651 |
| ±2 s | 0.5032 |
| ±5 s | 0.7495 |

### Workflow discovery

`src/process_discovery_final.py` groups similar work segments into recurring workflow types.

The final representation uses contextual UI information such as window titles, target fields, available text, and screen text. Dynamic values such as URLs, email addresses, dates, times, long numbers, and ID-like strings are masked.

Character-level TF-IDF is used because the logs contain Japanese UI text and mixed application strings. Agglomerative clustering with cosine distance is then applied, with the internal configuration balancing silhouette score and stability against a singleton penalty. Reorder stability is also checked so that workflow discovery does not depend on record ordering.

Dataset A holdout results for the final workflow-discovery configuration:

| Measure | Result |
|---|---:|
| Segments with evidence | 519 |
| Sessions | 13 |
| Semantic dimensions | 10,713 |
| Threshold | 0.60 |
| Clusters | 22 |
| Silhouette | 0.5338 |
| Singleton fraction | 0.0455 |
| Stability ARI | 1.0000 |
| Reorder stability ARI | 1.0000 |
| GT purity | 0.3554 |
| GT ARI | 0.1620 |

## Dataset B final result

The frozen Task 1 pipeline was then applied to Dataset B.

| Output | Result |
|---|---:|
| Sessions | 15 |
| Activities | 9,169 |
| Segments | 400 |
| Workflow clusters | 20 |
| Semantic dimensions | 4,294 |
| Silhouette | 0.3825 |
| Overlaps | 0 |
| Unresolved segments | 0 |
| Stability ARI | 1.0000 |
| Reorder stability ARI | 1.0000 |

The final required file is:

```text
outputs/segments.jsonl
```

Each record contains:

```json
{
  "session_id": "...",
  "start": "...",
  "end": "...",
  "label": "..."
}
```

Final integrity checks confirmed that all 400 records parsed correctly, required fields were present and correctly ordered with no missing values, timestamps were valid with no negative or zero durations, there were no overlaps or duplicate identical segments, chronological order was preserved per session, no conflicting labels were assigned to identical intervals, and no temporary `WORK_*` labels remained.

Segment-duration statistics:

| Statistic | Duration |
|---|---:|
| Minimum | 12.58 s |
| Median | 24.38 s |
| 95th percentile | 44.49 s |
| Maximum | 98.23 s |

Adjacent segments with the same workflow label are intentionally kept separate, since the same workflow label does not imply the same execution. The final output should also be read as a segmentation of the observed session spans; it does not claim that every second inside an interval has been independently proven to be business work.

## Task 2 - Workflow analysis

Two scripts form the main Task 2 analysis layer:

```text
src/task2_workflow_execution_analysis_v2.py
src/infer_business_types_v2.py
```

The analysis combines the extracted activities with the frozen segmentation output and records:

- workflow and execution counts
- session coverage
- recorded duration
- application footprint and application switching
- activity patterns
- recurring documents and files
- entity evidence
- semantic cues
- representative executions

The script also creates deterministic internal occurrence IDs, such as `WORKFLOW_006_EXEC_0001`. These are internal identifiers created by the analysis and are not source-system execution IDs.

The finalized analysis assigns every activity exactly once: all 9,169 activities across 400 segments, 15 sessions, and 20 workflow clusters are accounted for, with 0 unassigned.

Main outputs are stored under:

```text
outputs/dataset_b/task2_v2/
```

- `workflow_summary.csv`
- `execution_map.jsonl`
- `workflow_evidence.jsonl`
- `workflow_semantic_cues.jsonl`
- `task2_report.json`
- `task2_anomalies.json`

Dataset B contains no official business-process names, so the business interpretation stage uses repeated evidence rather than isolated keywords. Evidence includes recurring documents, recurring Excel files, repeated browser pages, recurring application combinations, and repeated UI text. Low-confidence workflows are deliberately left broad or ambiguous rather than being assigned unsupported business names.

The final confidence distribution was:

| Confidence | Workflows |
|---|---:|
| High | 9 |
| Medium | 1 |
| Low / ambiguous | 10 |

Examples of strongly evidenced workflows include:

- `WORKFLOW_003` - Expense calculation / settlement support: 17 occurrences across 7 sessions (~7.7 minutes recorded). Observed evidence included `expense_calc` in all 17 occurrences, Excel in all 17 occurrences, Edge in 16 occurrences, and accounting-system interaction in 12 occurrences.
- `WORKFLOW_010` - New-hire onboarding / employee joining verification: 41 occurrences across 9 sessions (~17.8 minutes recorded), with the `nyusha_checklist_shinsotsu_batch` reference recurring in 40 of the 41 occurrences.
- `WORKFLOW_004` - Monthly fixed-amount business-partner list review: 43 occurrences across 9 sessions (~16.8 minutes recorded), with repeated evidence including `getsujitsu_teigaku_torihikisaki_ichiran`.

The final Task 2 report is:


reports/report_task_2_final.md


The report documents, for each workflow, its ID, inferred business type, confidence, occurrence count, session coverage, recorded time, application footprint and switching, entity evidence, semantic cues, representative evidence, and an automation interpretation - including why particular workflows were considered for automation and why the final prototype was scoped around `WORKFLOW_003`.

### Automation candidate selected for Task 3

The selected workflow is `WORKFLOW_003` - Expense calculation / settlement support. It showed a repeated pattern involving source/accounting information, Excel-based calculation work, and accounting-system interaction. Since the logs did not provide the complete production accounting formula or a real accounting-system API, the prototype is intentionally scoped to the calculation, validation, review, and submission workflow around structured expense data, rather than pretending to implement the actual production accounting system.

## Automation prototypes

The repository contains **two automation prototypes**. They serve different business workflows and demonstrate two different integration styles.

### Automation 1 - Expense calculation and settlement

**Location:** `automation/`

Selected workflow:

```text
WORKFLOW_003 - Expense calculation / settlement support
```

The prototype processes structured expense data from CSV and Excel files.

The processing path is:

```text
Input files
    |
    v
Validation
    |
    v
Calculation
    |
    v
Exception detection
    |
    v
Review
    |
    v
Human approval
    |
    v
Mock submission
```

Supported input includes CSV, Excel, multiple files, directories, and multiple worksheets. The prototype accepts structured expense data with fields including:

```text
expense_id, employee_ref, department, expense_date, category, merchant,
project_code, payment_method, reimbursable, receipt_available, quantity,
unit_amount, currency, fx_rate_to_reporting, tax_rate, discount_rate,
source_reference
```

The demonstration calculation is:

```text
subtotal        = quantity × unit_amount
discount        = subtotal × discount_rate
taxable         = subtotal − discount
tax             = taxable × tax_rate
total           = taxable + tax
reporting_total = total × fx_rate_to_reporting
```

These formulas are prototype rules and are not presented as the company's confirmed accounting policy.

The prototype generates calculated output together with audit and context fields (source file, source sheet, source row, IDs, calculated amount, duplicate flags, receipt exceptions, amount exceptions, and validation status), plus aggregate analysis covering unique employees, departments, projects, and merchants, reimbursable versus non-reimbursable spend, average/median/minimum/maximum transaction values, receipt coverage, duplicate and exception counts, and breakdowns by employee, department, category, project, merchant, payment method, currency, and month.

The prototype uses an explicit processing state machine:

```text
INPUT
  |
  v
VALIDATED
  |
  v
READY_FOR_APPROVAL
  |
  v
APPROVED
  |
  v
SUBMITTED
```

Hard validation failures move the batch to `BLOCKED` instead of processing it silently. The prototype also includes deterministic batch IDs, duplicate checks, exception reporting, audit information, an explicit human-approval gate, and idempotent mock submission.

Validation used large synthetic inputs so the prototype was tested as a batch-processing workflow rather than only on a few sample rows:

| Input | Rows | Final state | Errors | Warnings |
|---|---:|---|---:|---:|
| Clean Excel | 10,000 | `READY_FOR_APPROVAL` | 0 | 0 |
| CSV | 5,000 | `READY` | 0 | 0 |
| Multi-sheet Excel | 10,000 | `READY_FOR_APPROVAL` | 0 | 0 |
| Anomaly-heavy Excel | 10,000 | `BLOCKED` | 14 | 5 |

The anomaly-heavy input was deliberately constructed to contain problematic records, and the prototype correctly blocked it rather than processing invalid data silently.

The clean 10,000-row batch was carried all the way through `READY_FOR_APPROVAL -> APPROVED -> SUBMITTED`, with the approval step recording the approver and approval reason. Mock submission was then run twice against the same batch; the second submission returned the same transaction identity, confirming idempotent behavior and preventing duplicate submission.

The automation test suite reported:

```text
5 / 5 tests passed
```

Useful commands:

```powershell
python automation\workflow003_automation.py self-test

python -m unittest discover -s automation\tests -p "test_*.py" -v
```

### Automation 2 - Supplier and contract operations

**Location:** `automation_2/`

The second prototype was built around the recurring `WORKFLOW_006` family found in the logs. This workflow appeared 64 times across 10 sessions and included supplier/business-partner and contract activities such as supplier registration, contract procedures, and termination-related work.

The prototype is an MCP-based operations copilot. It is designed around a sequence such as:

```text
Find business record
      |
      v
Inspect contracts and documents
      |
      v
Validate the request
      |
      v
Run policy and risk checks
      |
      v
Prepare a case
      |
      v
Human approval
      |
      v
Controlled submission
```

The MCP layer exposes tools for:

- searching and retrieving business partners
- listing and reading contracts
- checking request completeness
- finding duplicate suppliers
- assessing contract requests
- preparing cases
- requesting and recording approval
- submitting approved cases
- retrieving case status and audit history

The supported request types are:

```text
supplier_registration
contract_creation
contract_amendment
contract_termination
```

The business service, rather than the language model, handles deterministic validation, policy checks, state changes, and approval enforcement.

The prototype uses vendor-neutral interfaces:

- `PartnerDirectory`
- `ContractSystem`
- `DocumentStore`
- `WorkflowSystem`
- `SignatureProvider`
- `AuditStore`

The demo implementations use SQLite and mock adapters. The architecture can therefore be connected later to approved enterprise systems without changing the MCP tool contract.

#### Safety and control points

Automation 2 deliberately does not allow an AI call to become an unrestricted write operation.

Controls include:

- duplicate-supplier checks
- required-field validation
- enhanced review for large contract-value changes
- blocking termination when open obligations are reported
- explicit approval before submission
- idempotency for repeated submissions
- fail-closed handling for integration failures
- least-privilege tool access
- no credentials stored in source code
- audit logging

The case state machine is:

```text
DRAFT
  |
  v
PENDING_APPROVAL
  |
  v
APPROVED
  |
  v
SUBMITTED
```

Hard validation failures enter `BLOCKED`.

The prototype uses mock downstream systems and does not claim to connect to a company's real SAP, ServiceNow, SharePoint, Docusign, or other production environment.

For the MCP runtime, install the Python SDK in the project's virtual environment:

```powershell
pip install "mcp[cli]"
```

Then use:

```powershell
python verify_mcp_runtime.py
```

For interactive inspection during development:

```powershell
mcp dev contract_ops_mcp\mcp_server\server.py
```

More detailed information about extending Automation 2 to real enterprise systems is in:

```text
automation_2/docs/integration_guide_automation2.md
```

## Repository structure

A simplified view of the repository is:

```text
.
├── src/
│   ├── activities.py
│   ├── case_segment_ml_v6.py
│   ├── process_discovery_final.py
│   ├── task2_workflow_execution_analysis_v2.py
│   ├── infer_business_types_v2.py
│   └── finalize_segments.py
│
├── automation/
│   ├── workflow003_automation.py
│   └── tests/
│       └── test_workflow003_corrected.py
│
├── automation_2/
│   ├── config/
│   │   ├── integrations.json
│   │   └── policy.json
│   ├── contract_ops_mcp/
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── mock.py
│   │   │   ├── rest.py
│   │   │   └── signature.py
│   │   ├── mcp_server/
│   │   │   ├── __init__.py
│   │   │   └── server.py
│   │   ├── __init__.py
│   │   ├── demo.py
│   │   ├── models.py
│   │   ├── policy.py
│   │   ├── ports.py
│   │   ├── service.py
│   │   └── store.py
│   ├── docs/
│   │   └── integration_guide_automation2.md
│   ├── tests/
│   │   ├── test_engine_hundreds.py
│   │   ├── test_security_and_connectors.py
│   │   └── test_server_contract.py
│   ├── .env.example
│   ├── generate_demo_data.py
│   ├── pyproject.toml
│   ├── readme_automation2.md
│   ├── requirements.txt
│   ├── smoke_demo.py
│   └── verify_mcp_runtime.py
│
├── outputs/
│   ├── segments.jsonl
│   └── dataset_b/
│       └── task2_v2/
│           ├── workflow_summary.csv
│           ├── execution_map.jsonl
│           ├── workflow_evidence.jsonl
│           ├── workflow_semantic_cues.jsonl
│           ├── task2_report.json
│           └── task2_anomalies.json
│
├── reports/
│   └── report_task_2_final.md
│
├── Deliverable_Documents/
├── tests/
├── data/
├── WORK_LOG.md
├── requirements.txt
└── README.md
```

Exploratory scripts from development are not part of the finalized execution path. Large raw datasets and generated files are excluded through `.gitignore` where appropriate; the required `outputs/segments.jsonl` is intentionally retained as a project deliverable.

## Quick start

From the repository root:

```powershell
.venv\Scripts\activate
```

The final Task 1 output is already available at:

```text
outputs/segments.jsonl
```

Run the first automation self-test:

```powershell
python automation\workflow003_automation.py self-test
```

Run its tests:

```powershell
python -m unittest discover -s automation\tests -p "test_*.py" -v
```

For Automation 2, install the MCP SDK if it is not already installed:

```powershell
pip install "mcp[cli]"
```

Then run its runtime verifier from the `automation_2` directory:

```powershell
python verify_mcp_runtime.py
```

## Final deliverables

| Deliverable | Purpose |
|---|---|
| `outputs/segments.jsonl` | Required Task 1 segmented workflow output for Dataset B |
| `reports/report_task_2_final.md` | Task 2 workflow analysis and automation assessment |
| `automation/workflow003_automation.py` | Working Task 3 automation prototype - expense calculation and settlement |
| `automation/tests/test_workflow003_corrected.py` | Automation 1 test suite |
| `automation_2/contract_ops_mcp/` | Working Task 3 automation prototype - MCP-based supplier and contract operations |
| `automation_2/tests/` | Automation 2 test suite |
| `WORK_LOG.md` | Detailed development history, experiments, decisions, and debugging record |

## Final project results

### Task 1

- 15 Dataset B sessions
- 9,169 extracted activities
- 400 final segments
- 20 discovered workflow labels
- 0 overlaps
- 0 unresolved segments

### Task 2

- 20 workflow clusters
- 9 high-confidence business interpretations
- 1 medium-confidence interpretation
- 10 low or ambiguous interpretations

### Task 3

Two working prototypes are included:

1. **Expense calculation / settlement support** - batch validation, calculation, review, approval, and mock submission.
2. **Supplier and contract operations** - MCP-based business-record lookup, policy checks, case preparation, human approval, and controlled mock submission.

## Limitations

The logs do not expose the complete production data model, APIs, approval rules, authentication model, or business policies of the organization.

For that reason:

- Dataset B workflow names are evidence-based interpretations, not official process names.
- Recorded time should not be treated as a production ROI estimate.
- Some workflows remain ambiguous.
- Automation 1 uses illustrative expense rules rather than confirmed accounting policy.
- Automation 2 uses mock enterprise systems rather than production integrations.
- The segmentation model is validated, but it does not represent perfect recovery of ground-truth business boundaries.

The purpose of the repository is to show a complete path from raw desktop activity to workflow discovery, business-process analysis, and controlled automation.
