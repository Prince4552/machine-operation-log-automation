# NAME: PRIYANSHU KRIPASHANKAR SINGH

# ROLL NO:BM24BTECH11020

# Application EMAIL: bm24btech11020@iith.ac.in

# University:IIT HYDERABAD/ DEPARTMENT: BIOMEDICAL ENGINEERING.



# 

# I'm Beside You — Operation Log Automation Task.





An end-to-end pipeline for converting low-level desktop operation logs into **work segments and recurring workflow types**, analysing those workflows for automation opportunities, and building a working automation prototype for one selected process.

The repository contains the finalized implementation for all three parts of the task:


Raw desktop logs
      │
      ▼
Activity extraction
      │
      ▼
Boundary-based segmentation
      │
      ▼
Workflow discovery
      │
      ▼
Validated segments.jsonl
      │
      ├──────────────► Task 2: workflow analysis
      │                         │
      │                         ▼
      │                  automation candidate
      │                         │
      │                         ▼
      └──────────────► Task 3: working prototype
```

The **work log** documents the development history, experiments, failures, and debugging process. This README is intentionally different: it documents the **final project, its components, how they fit together, what each script does, what it produces, and how the final results were obtained**.

\---

## 1\. Project overview

The input consists of desktop-operation logs generated while people perform work on their computers. A raw event is a low-level recorded operation such as a click, keystroke, application switch, clipboard action, browser event, or shortcut.

The main challenge is to recover meaningful work from those low-level events.

The final project separates this into four concepts:


Event
  ↓
Activity
  ↓
Work segment / execution
  ↓
Workflow type/process
```

A **segment** is the contiguous interval of time in which some execution of a particular process started and suspended . 
A **workflow type** is the recurring kind of work represented by similar segments.

The final system is therefore not simply a time-gap splitter. It first creates a stable activity representation, detects boundaries between consecutive activities, discovers recurring workflow types, and then analyses those workflows at the business-process level.

\---

# 2\. Datasets

## Dataset A

Dataset A is the labelled dataset and is used for development and evaluation.

* \~63 sessions
* \~162,000 raw events
* Ground truth available

Dataset A is used to:

* validate activity extraction,
* train and evaluate the segmentation model,
* compare workflow representations,
* select the final workflow-discovery representation,
* and freeze the pipeline before applying it to Dataset B.

## Dataset B

Dataset B is the unlabeled dataset used for the final discovery and analysis.

* 15 sessions
* \~20,000 raw events
* No ground truth

Dataset B's workflow types are discovered directly from B. Dataset A's process labels are **not copied into B**.

\---

# 3\. Final pipeline

**The finalized Task 1 pipeline is:**


Dataset events
    │
    ▼
src/activities.py
    │
    ▼
Atomic activities
    │
    ▼
src/case\_segment\_ml\_v6.py
    │
    ▼
Contiguous work segments
    │
    ▼
src/process\_discovery\_final.py
    │
    ▼
Workflow labels
    │
    ▼
src/finalize\_segments.py
    │
    ▼
outputs/segments.jsonl
```

**Task 2 then builds an analysis layer on top of the frozen Task 1 output:**


activities + segments.jsonl
          │
          ▼
src/task2\_workflow\_execution\_analysis\_v2.py
          │
          ▼
workflow / execution evidence
          │
          ▼
src/infer\_business\_types\_v2.py
          │
          ▼
human-readable workflow interpretations
          │
          ▼
Task 2 workflow catalogue + report


Task 3 uses the selected workflow from Task 2:


WORKFLOW\_003
Expense calculation / settlement support
          │
          ▼
automation/workflow003\_automation.py
          │
          ▼
validation → calculation → exceptions
          → approval → mock submission
4. Task 1 — Activity extraction

## `src/activities.py`

This is the frozen activity-extraction layer.

It converts low-level raw events into atomic activities such as:

```text
APP\_SWITCH
CLICK
COPY
SHORTCUT
SCROLL
TEXT\_ENTRY
OTHER
```

The purpose is to reduce the raw event stream to a representation that is detailed enough for segmentation but much easier to reason about than individual low-level events.

The activity extractor was validated on Dataset A before being frozen. In a representative session:

```text
2,348 raw events → 388 activities
```

The text reconstruction check also matched the expected keyboard-derived text in all 96 tested cases.

### Produces

The activity layer is consumed by the segmentation and Task 2 analysis scripts. The exact generated intermediate files are kept under the project's output/data structure rather than being part of the required final submission format.

\---

# 5\. Task 1 — Final segmentation

## `src/case\_segment\_ml\_v6.py`

This is the finalized segmentation model.

Instead of asking whether two arbitrary activities belong to the same process, it predicts whether there is a **work boundary between two consecutive activities**.

For:


Activity A → Activity B


the model predicts:


same segment // ie part of same execution/process


or:


new segment starts here


This formulation directly produces contiguous output intervals.

### Model

* **Logistic Regression**
* **Session-level train/validation/test split**
* **40 sessions: training**
* **10 sessions: validation**
* **13 sessions: held-out evaluation**

### Final settings


Threshold      : 0.65
Minimum        : 12 seconds
Boundary mode  : previous activity end


### Held-out transition performance

|Metric|Result|
|-|-:|
|Precision|0.9788|
|Recall|0.9105|
|F1|0.9434|
|ROC-AUC|0.9307|
|PR-AUC|0.9864|

### Boundary F1

|Tolerance|F1|
|-|-:|
|±0.5 s|0.4503|
|±1 s|0.4651|
|±2 s|0.5032|
|±5 s|0.7495|

The final v6 implementation is frozen and is the segmentation backbone used for Dataset B.



# 6\. Task 1 — Workflow discovery

## `src/process\_discovery\_final.py`

Segmentation answers **where the work units are**. This script answers **which work units represent the same kind of work**.



The final approach is semantic-first.

It uses UI/context information such as:

* window titles,
* target fields,
* available text,
* screen text.

Dynamic values are masked so the representation does not simply memorize:

* URLs,
* email addresses,
* dates,
* times,
* long numeric values,
* ID-like strings.

### Representation

Character-level TF-IDF is used because the logs contain Japanese UI text and mixed application strings.

### Clustering

Agglomerative clustering with cosine distance is used.

The internal configuration balances:

silhouette
+ stability
− singleton penalty


Reorder stability is also checked so that workflow discovery is not dependent on record ordering.

### Dataset A validation

Final holdout result:

```text
Segments with evidence : 519
Sessions               : 13
Semantic dimensions    : 10,713
Threshold              : 0.60
Clusters               : 22
Silhouette             : 0.5338
Singleton fraction     : 0.0455
Stability ARI          : 1.0000
Reorder stability ARI  : 1.0000
GT purity              : 0.3554
GT ARI                 : 0.1620
```

The semantic-first version is the frozen workflow-discovery implementation used on Dataset B.

\---

# 7\. Task 1 — Dataset B result

The frozen pipeline was applied to Dataset B without changing the algorithms.

### Activity extraction


9,169 activities
15 sessions
```

### Segmentation


400 segments
15 sessions


### Workflow discovery


400 segments with evidence
15 sessions
4,294 semantic dimensions
threshold = 0.60
20 workflow clusters
silhouette = 0.3825
singleton fraction = 0
stability ARI = 1.0000
reorder stability = 1.0000


The temporary segmentation identifiers (`WORK\_\*`) were replaced by the final workflow labels.



# 8\. Final required output

## `outputs/segments.jsonl`

This is the main Task 1 deliverable.

Each line contains exactly four fields:

```json
{
  "session\_id": "...",
  "start": "...",
  "end": "...",
  "label": "..."
}
```

Final validation:

```text
Sessions        : 15
Segments        : 400
Workflow labels : 20
Overlaps        : 0
Unresolved      : 0
```

Independent integrity checks confirmed:

* 400/400 JSON records parsed successfully
* correct required fields and ordering
* no missing values
* 15 sessions
* 20 workflow labels
* no temporary `WORK\_\*` labels
* no invalid timestamps
* no negative or zero durations
* no overlaps
* no duplicate identical segments
* chronological order preserved per session
* no conflicting labels on identical intervals

### Segment-duration statistics


Minimum : 12.58 s
Median  : 24.38 s
95th    : 44.49 s
Maximum : 98.23 s


Adjacent segments with the same workflow label are intentionally kept separate because:


same workflow label ≠ same execution


The final output should also be interpreted as a segmentation of the observed session spans; it does not imply that every second inside an interval has independently been proven to be business work.



# 9\. Task 2 — Workflow and execution analysis

## `src/task2\_workflow\_execution\_analysis\_v2.py`

This script builds the analysis layer on top of the frozen Task 1 output.

It combines the extracted activities with `segments.jsonl` and produces workflow-level and execution-level evidence.

The analysis includes:

* workflow occurrence count,
* session count,
* recorded duration,
* application footprint,
* application switches,
* activity counts,
* activity patterns,
* entity evidence,
* semantic/process evidence,
* representative execution evidence.

It also creates deterministic inferred occurrence IDs such as:


WORKFLOW\_006\_EXEC\_0001


These are internal occurrence IDs created by the analysis and are **not source-system execution IDs**.

### Main outputs


outputs/dataset\_b/task2\_v2/
├── workflow\_summary.csv
├── execution\_map.jsonl
├── workflow\_evidence.jsonl
├── workflow\_semantic\_cues.jsonl
├── task2\_report.json
└── task2\_anomalies.json


### Final assignment check

The finalized analysis assigns every activity exactly once:

```text
Activities           : 9,169
Final segments       : 400
Sessions             : 15
Workflow clusters    : 20
Assigned exactly once: 9,169
Unassigned           : 0
```

\---

# 10\. Task 2 — Business-process interpretation

## `src/infer\_business\_types\_v2.py`

Dataset B does not contain ground-truth business-process names. This script therefore uses repeated evidence within each discovered workflow to suggest a human-readable interpretation.

The inference is deliberately conservative. Repeated evidence is preferred over isolated keywords.

Examples of evidence include:

* recurring documents,
* recurring Excel files,
* repeated browser pages,
* recurring application combinations,
* repeated UI text.

### Final confidence distribution

```text
High confidence      : 9 workflows
Medium confidence    : 1 workflow
Low / ambiguous      : 10 workflows
```

Low-confidence workflows are left broad or ambiguous rather than being assigned unsupported business names.

### Examples of strongly evidenced workflows

#### `WORKFLOW\_003`

**Expense calculation / settlement support**

Observed evidence:

* `expense\_calc` in all 17 occurrences
* Excel in all 17 occurrences
* Edge in 16 occurrences
* accounting-system interaction in 12 occurrences


Occurrences : 17
Sessions    : 7
Recorded    : \~7.7 minutes
Confidence  : High
```

#### `WORKFLOW\_010`

**New-hire onboarding / employee joining verification**

Strong repeated evidence included:


nyusha\_checklist\_shinsotsu\_batch
```

in 40 of 41 occurrences.


Occurrences : 41
Sessions    : 9
Recorded    : \~17.8 minutes
Confidence  : High
```

#### `WORKFLOW\_004`

**Monthly fixed-amount business-partner list review**

```
Occurrences : 43
Sessions    : 9
Recorded    : \~16.8 minutes
```

with repeated evidence including:

```text
getsujitsu\_teigaku\_torihikisaki\_ichiran
```

\---

# 11\. Task 2 — Business workflow catalogue and report

The final human-readable workflow catalogue documents, for each workflow:

* workflow ID,
* inferred business type,
* confidence,
* occurrence count,
* session coverage,
* recorded time,
* application footprint,
* application switching,
* entity evidence,
* semantic cues,
* representative evidence,
* automation interpretation.

The final Task 2 report is:

```
reports/report\_task\_2\_final.md
```

The report also documents why particular workflows were considered for automation and why the final prototype was scoped around `WORKFLOW\_003`.

\---

# 12\. Automation candidate selected for Task 3

The selected workflow is:

```
WORKFLOW\_003
Expense calculation / settlement support
```

The observed workflow showed a repeated pattern involving source/accounting information, Excel-based calculation work, and accounting-system interaction.

The logs did not provide the complete production accounting formula or a real accounting-system API. Therefore, the prototype is intentionally scoped to the **calculation, validation, review, and submission workflow around structured expense data**, rather than pretending to implement the actual production accounting system.

\---

# 13\. Task 3 — Automation prototype

## `automation/workflow003\_automation.py`

The prototype implements the following flow:

```
Input files
    ↓
Validation
    ↓
Calculation
    ↓
Exception detection
    ↓
Review output
    ↓
Human approval
    ↓
Mock submission
```

It supports:

* CSV input,
* Excel input,
* multiple files,
* directory-level batch processing,
* multiple worksheets in an Excel workbook.

\---

## 13.1 Input fields

The prototype accepts structured expense data including:

```

expense\_id
employee\_ref
department
expense\_date
category
merchant
project\_code
payment\_method
reimbursable
receipt\_available
quantity
unit\_amount
currency
fx\_rate\_to\_reporting
tax\_rate
discount\_rate
source\_reference
```

\---

## 13.2 Calculation rules

The demonstration calculation is configurable and uses:

```
subtotal        = quantity × unit\_amount
discount        = subtotal × discount\_rate
taxable         = subtotal − discount
tax             = taxable × tax\_rate
total           = taxable + tax
reporting\_total = total × fx\_rate\_to\_reporting
```

These are **prototype rules**, not claims about the company's actual accounting policy.

\---

## 13.3 Validation and analytics

The prototype generates calculated output together with audit/context fields such as:

* source file,
* source sheet,
* source row,
* IDs,
* calculated amount,
* duplicate flags,
* potential duplicate indicators,
* receipt exceptions,
* amount exceptions,
* validation status.

It also produces aggregate analysis such as:

* unique employees,
* departments,
* projects,
* merchants,
* reimbursable/non-reimbursable spend,
* average/median/minimum/maximum transaction,
* receipt coverage,
* duplicate counts,
* exception counts,
* breakdowns by employee, department, category, project, merchant, payment method, currency and month.

\---

# 14\. Automation state machine

The prototype uses explicit processing states:

```
INPUT
  ↓
VALIDATED
  ↓
READY\_FOR\_APPROVAL
  ↓
APPROVED
  ↓
SUBMITTED
```

Hard validation failures move the batch to:

``
BLOCKED
```

The prototype also includes:

* deterministic batch IDs,
* exception reporting,
* audit logging,
* a human approval gate,
* idempotent submission,
* a mock submission layer.

No real accounting-system transaction is created.

\---

# 15\. Automation validation

Large synthetic inputs were used so the prototype was tested as a batch-processing workflow rather than only on a few sample rows.

Test inputs included:

```
enterprise\_expenses\_10000.xlsx
enterprise\_expenses\_multi\_sheet\_10000.xlsx
enterprise\_expenses\_anomalies\_10000.xlsx
enterprise\_expenses\_5000.csv
```

### End-to-end results

|Input|Rows|Final state|Errors|Warnings|
|-|-:|-|-:|-:|
|Clean Excel|10,000|`READY\_FOR\_APPROVAL`|0|0|
|CSV|5,000|`READY`|0|0|
|Multi-sheet Excel|10,000|`READY\_FOR\_APPROVAL`|0|0|
|Anomaly-heavy Excel|10,000|`BLOCKED`|14|5|

The anomaly-heavy batch was intentionally designed to contain problematic records, and the prototype correctly blocked it instead of silently processing invalid data.

\---

# 16\. Automation test suite

## `automation/tests/test\_workflow003\_corrected.py`

The final test suite covers:

* directory batch processing,
* duplicate and unsupported-currency blocking,
* calculation correctness and multi-sheet Excel input,
* idempotent mock submission,
* warning handling on an otherwise valid submission path.

Run:

```powershell
python -m unittest discover -s automation\\tests -p "test\_\*.py" -v
```

Final result:

```
5 tests passed
OK
```

The prototype also has a built-in preflight self-test:

```powershell
python automation\\workflow003\_automation.py self-test
```

Expected result:

```
Preflight WORKFLOW\_003 automation v2 self-test: PASS (7 assertions)
```

\---

# 17\. Approval and submission flow

The final clean 10,000-row batch successfully completed:

```
READY\_FOR\_APPROVAL
        ↓
APPROVED
        ↓
SUBMITTED
```

The approval records the approver and approval reason.

Mock submission was then executed twice against the same batch. The second submission returned the same transaction identity, demonstrating idempotent behavior and preventing duplicate submission for the same batch.

\---

# 18\. Repository structure

A simplified view of the finalized repository is:

```
.
├── src/
│   ├── activities.py
│   ├── case\_segment\_ml\_v6.py
│   ├── process\_discovery\_final.py
│   ├── task2\_workflow\_execution\_analysis\_v2.py
│   ├── infer\_business\_types\_v2.py
│   └── finalize\_segments.py
│
├── automation/
│   ├── workflow003\_automation.py
│   └── tests/
│       └── test\_workflow003\_corrected.py
│
├── outputs/
│   └── segments.jsonl
│
├── reports/
│   └── report\_task\_2\_final.md
│
└── WORK\_LOG.md
```

**Exploratory/debug scripts from development are not part of the finalized execution path**.

**Large raw datasets and generated artifacts are excluded through `.gitignore` where appropriate. The required final `outputs/segments.jsonl` is intentionally retained as a project deliverable.**

\---

# 19\. Final deliverables

The important final outputs are:

|Deliverable|Purpose|
|-|-|
|`outputs/segments.jsonl`|Required Task 1 segmented workflow output for Dataset B|
|`reports/report\_task\_2\_final.md`|Task 2 workflow analysis and automation assessment|
|`automation/workflow003\_automation.py`|Working Task 3 automation prototype|
|`automation/tests/test\_workflow003\_corrected.py`|Final automation test suite|
|`WORK\_LOG.md`|Detailed development history, experiments, decisions, and debugging record|

Task 2 intermediate analysis is stored under:

```
outputs/dataset\_b/task2\_v2/
```

with workflow summaries, execution maps, semantic evidence, anomaly information, and the structured Task 2 report data.

\---

# 20\. Final project results

## Task 1

```
Dataset B sessions : 15
Activities         : 9,169
Segments           : 400
Workflow labels    : 20
Overlaps           : 0
Unresolved         : 0
```

## Task 2

```
Workflow clusters       : 20
High-confidence types   : 9
Medium-confidence types : 1
Low/ambiguous types     : 10
```

Important strongly evidenced workflows include:

```text
WORKFLOW\_003
Expense calculation / settlement support

WORKFLOW\_010
New-hire onboarding / employee joining verification

WORKFLOW\_004
Monthly fixed-amount business-partner list review
```

## Task 3

```
Selected workflow:
WORKFLOW\_003 — Expense calculation / settlement support

Prototype validation:
10,000-row Excel       → READY\_FOR\_APPROVAL
5,000-row CSV          → READY
10,000-row multi-sheet → READY\_FOR\_APPROVAL
10,000-row anomaly set → BLOCKED

Automated test suite:
5 / 5 passed

Submission:
Idempotent mock submission verified
```

\---

# 21\. Important limitations

The final results should be interpreted within the information available in the provided logs.

### Dataset B has no ground truth

The 20 workflow labels are internally discovered workflow clusters. The business names are evidence-based interpretations, not official company process names.

### Recorded time is not production ROI

The durations in the logs are useful for comparing observed workload, but they are not sufficient to claim real production savings.

### Some workflows remain ambiguous

Where the evidence was mixed, the project deliberately avoids inventing a more specific process name.

### Automation rules are illustrative

The expense formulas demonstrate the automation architecture. They are not presented as the company's confirmed accounting policy.

### No production accounting integration

Submission is mocked because the real accounting API, authentication model, production rules, reconciliation behavior, rollback strategy, and deployment environment were not available in the task data.

### Segmentation is not perfect

The final segmentation model is measurable and validated, but the underlying problem remains ambiguous in some cases. The repository therefore exposes the actual evaluation results rather than presenting the segmentation as exact ground truth recovery.

\---

# 22\. Quick start

The project uses Python and a virtual environment for execution.

From the repository root:

```powershell
.venv\\Scripts\\activate
```

Run the automation self-test:

```powershell
python automation\\workflow003\_automation.py self-test
```

Run the automation test suite:

```powershell
python -m unittest discover -s automation\\tests -p "test\_\*.py" -v
```

The final Task 1 deliverable is already available at:

```text
outputs/segments.jsonl
```

\---

# 23\. Final architecture in one view

```
                    ┌──────────────────────┐
                    │   Dataset A / B      │
                    │  Raw operation logs   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ activities.py        │
                    │ Atomic activities    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ case\_segment\_ml\_v6   │
                    │ Boundary detection   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ process\_discovery\_   │
                    │ final.py             │
                    │ Workflow discovery  │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ finalize\_segments.py │
                    │ Validation + output  │
                    └──────────┬───────────┘
                               │
                               ▼
                    outputs/segments.jsonl
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
                 ▼                           ▼
        Task 2 analysis             Task 2 business types
                 │                           │
                 └─────────────┬─────────────┘
                               ▼
                    Automation candidate
                               │
                               ▼
                    WORKFLOW\_003
                               │
                               ▼
                workflow003\_automation.py
                               │
                               ▼
             Validate → Calculate → Review
                               │
                               ▼
                   Approve → Mock Submit


This is the finalized project structure: **recover the work, discover the workflows, analyse the business processes, and demonstrate a practical automation path for one of them.**

