# NAME: PRIYANSHU KRIPASHANKAR SINGH

# ROLL NO:BM24BTECH11020

# Application EMAIL: bm24btech11020@iith.ac.in

# University:IIT HYDERABAD/ DEPARTMENT: BIOMEDICAL ENGINEERING.





# Final Report — Dataset B Analysis and Automation Prototype

## 1\. What I was trying to solve

The main goal of the task was not simply to split a desktop recording into time ranges. I had to recover meaningful units of business work from continuous operation logs, understand what kinds of work people were doing, identify opportunities for automation, and then build a working prototype for one of those opportunities.

For Dataset B, there was no ground truth. That meant I had to be careful not to present inferred process names as facts. I therefore treated the output labels from process discovery as internal workflow IDs and used repeated application, window, document, and activity evidence to infer human-readable process types.

The final Step 1 output is `outputs/segments.jsonl`. Task 2 and the prototype were built around that frozen output.

\---

# 2\. How I moved from Step 1 to Task 2

The final Dataset B result contains:

|Metric|Result|
|-|-:|
|Sessions|15|
|Atomic activities|9,169|
|Inferred workflow occurrences|400|
|Workflow clusters|20|
|Recorded segment time|\~176.2 minutes|
|Activities assigned to exactly one segment|9,169|
|Activities left unassigned|0|
|Segment overlaps|0|

I also kept three concepts separate because they mean different things:

**Workflow cluster** — for example, `WORKFLOW\_003`. This is an internal cluster ID produced by unsupervised process discovery. It is not the original business-process name.

**Inferred execution occurrence** — for example, `WORKFLOW\_003\_EXEC\_0001`. This is an ID that I generated for one inferred contiguous occurrence. It is not an original case ID or execution ID from the source system.

**Business-process type** — a human-readable interpretation such as "Expense calculation / settlement support", based on recurring evidence in the cluster.

This distinction was important because Dataset B does not give me enough information to claim that a particular segment is "Employee-001 registration" or "Invoice-002 approval" unless that identity is explicitly recoverable from the logs.

\---

# 3\. What I found in Dataset B

The 20 discovered workflow clusters were not equally clear.

Some had strong recurring evidence. For example:

* `WORKFLOW\_003` repeatedly used an `expense\_calc` Excel artifact and the financial-accounting system.
* `WORKFLOW\_010` repeatedly used a new-hire checklist together with the HR system.
* `WORKFLOW\_004` repeatedly used the monthly fixed-amount business-partner list.
* `WORKFLOW\_016` repeatedly contained an administrator-permission request procedure.

Other clusters mixed several systems or contained too little distinctive evidence to justify a narrow process name. I kept those clusters generic rather than inventing a business meaning.

The human-readable interpretation of the major clusters was:

|Workflow|Inferred business type|Confidence|Occurrences|Sessions|Recorded time|
|-|-|-|-:|-:|-:|
|`WORKFLOW\_006`|Supplier / business-partner / contract administration|High|64|10|26.2 min|
|`WORKFLOW\_014`|Outsourced-work acceptance / expense administration|High|43|8|18.7 min|
|`WORKFLOW\_004`|Monthly fixed-amount business-partner list review|High|43|9|16.8 min|
|`WORKFLOW\_010`|New-hire onboarding / employee joining verification|High|41|9|17.8 min|
|`WORKFLOW\_007`|HR/order-system administrative review|Low|32|10|12.9 min|
|`WORKFLOW\_005`|HR-system administrative handling|Low|26|4|12.9 min|
|`WORKFLOW\_008`|HR-system administrative handling|Low|22|7|10.7 min|
|`WORKFLOW\_018`|Mixed HR/order/accounting administrative handling|Low|21|2|8.9 min|
|`WORKFLOW\_003`|Expense calculation / settlement support|High|17|7|7.7 min|
|`WORKFLOW\_015`|Expense settlement confirmation|High|15|8|6.1 min|
|`WORKFLOW\_001`|Mixed administrative handling|Low|13|10|4.3 min|
|`WORKFLOW\_002`|Mixed financial/HR administrative handling|Low|12|9|6.7 min|
|`WORKFLOW\_013`|Childcare / nursing-care leave administration|High|11|4|5.0 min|
|`WORKFLOW\_016`|Administrator access / permission request|High|11|4|6.9 min|
|`WORKFLOW\_009`|Mixed HR/order-system administrative handling|Low|9|7|5.3 min|
|`WORKFLOW\_011`|Budget analysis / financial planning support|High|7|1|2.9 min|
|`WORKFLOW\_012`|Financial-accounting administrative handling|Low|5|5|3.1 min|
|`WORKFLOW\_017`|Mixed administrative handling|Low|3|2|1.1 min|
|`WORKFLOW\_019`|HR case/comment entry or confirmation|Medium|3|2|1.1 min|
|`WORKFLOW\_020`|Order/inventory-system administrative handling|Low|2|1|1.0 min|

The detailed evidence catalogue is kept separately in `outputs/dataset\_b/task2\_business/task2\_business\_workflow\_catalog.md`.

The recorded minutes are useful for comparing workflows inside this dataset. I did not treat them as direct production time savings because the README notes that the recordings come from a test environment with shorter waiting times than production.

\---

# 4\. How I selected the automation candidates

I did not simply choose the workflows with the largest number of occurrences.

I considered:

1. frequency;
2. recorded time;
3. clarity of the business-work pattern;
4. repeatability;
5. cross-application complexity;
6. amount of human judgment involved;
7. implementation and governance risk;
8. most importantly, whether I could build a credible end-to-end prototype in the time remaining.

That last point mattered a lot. A very large process is not automatically the right prototype target if reproducing its real system integration would take days.

\---

# 5\. Automation candidates

## 1\. WORKFLOW\_003 — Expense calculation / settlement support

This became my prototype target.

There were 17 inferred occurrences across 7 sessions and about 7.7 minutes of recorded activity.

The strongest evidence was unusually consistent: the same `expense\_calc` Excel artifact appeared in all 17 occurrences. Microsoft Excel appeared in all 17, the financial-accounting system in 12, and Microsoft Edge in 16.

The visible pattern suggested a repeated flow around:

`source/accounting information -> Excel calculation -> result preparation -> accounting-system interaction`

The workflow was therefore a good candidate for automating the repetitive calculation and preparation part while keeping final approval under human control.

### Why I chose it for the prototype

It gave me the best balance of:

* a repeated business artifact;
* a recognizable workflow;
* structured data;
* deterministic computation;
* a relatively small number of core decisions;
* and a realistic chance of finishing a reliable prototype quickly.

It also allowed me to demonstrate a complete automation pipeline without pretending that I had access to the company's real accounting API.

\---

## 2\. WORKFLOW\_010 — New-hire onboarding / employee joining verification

This workflow had 41 occurrences across 9 sessions and about 17.8 recorded minutes.

The strongest evidence was the repeated `nyusha\_checklist\_shinsotsu\_batch` artifact, which appeared in 40 of 41 occurrences, together with the HR system.

This is a strong automation candidate because the work appears to involve repeated movement from a checklist/source document into structured HR-system information.

I did not choose it for the first prototype because it involves sensitive employee information, more applications, and HR-specific business rules that are not exposed by the logs. A real end-to-end implementation would therefore need more integration and governance work.

\---

## 3\. WORKFLOW\_004 — Monthly fixed-amount business-partner list review

This workflow had 43 occurrences across 9 sessions and about 16.8 recorded minutes.

The recurring `getsujitsu\_teigaku\_torihikisaki\_ichiran` artifact appeared in 31 occurrences. The workflow repeatedly involved the financial-accounting system, Edge, Word, and supporting systems.

This is naturally suited to report generation, data extraction and validation.

I placed it behind the first candidate because the workflow spans many applications and the logs do not expose enough of the underlying business rules to reproduce the complete real process quickly.

\---

# 6\. Why I did not choose the largest workflow

`WORKFLOW\_006` had the largest observed workload:

* 64 occurrences;
* 10 sessions;
* about 26.2 recorded minutes.

It looked attractive based on volume alone, but closer inspection showed that the cluster contained several related procedures:

* `shinkuitorihikisaki\_touroku\_tetsuzuki`
* `shinkui\_keiyaku\_tetsuzuki`
* `keiyaku\_kaijo\_tetsuzuki`

The workflow also involved six applications and substantial application switching.

I therefore treated it as a potentially high-impact future automation area, but not a good four-hour prototype target. I would first split it into smaller procedures before automating it.

The same reasoning applied to `WORKFLOW\_014`: it had a high workload, but its evidence covered more than one related work family.

Smaller workflows were also excluded when their business meaning was unclear, their session coverage was too narrow, or the likely automation would require an important human authorization decision.

\---

# 7\. Step 3 — What I actually built

## Chosen workflow

**WORKFLOW\_003 — Expense calculation / settlement support**

I deliberately did not try to build an "AI accounting agent" or reproduce the whole accounting system.

Instead, I built a deterministic Python automation pipeline with the following scope:

```
Excel / CSV input
      |
      v
Schema validation
      |
      v
Business-rule validation
      |
      v
Expense calculations
      |
      v
Exception detection
      |
      v
Excel + CSV output and analytics
      |
      v
READY\_FOR\_APPROVAL
      |
      v
Human approval
      |
      v
Mock submission
      |
      v
Audit trail / final state
```

The program also supports processing an entire directory, so the intended usage is closer to:

> Put one or several expense files in the input location and run the program. It processes the files, creates the output package, and reports which batches are ready, blocked, or failed.

For Excel workbooks, it can process multiple worksheets. It also accepts CSV files.

\---

# 8\. What the automation calculates

The prototype uses transparent, configurable calculation rules.

For each expense row:

`subtotal = quantity × unit\_amount`

`discount = subtotal × discount\_rate`

`taxable\_amount = subtotal − discount`

`tax = taxable\_amount × tax\_rate`

`calculated\_amount = taxable\_amount + tax`

`reporting\_amount = calculated\_amount × approved FX rate`

The output workbook also documents these rules in a separate `Calculation\_Rules` sheet.

These are demonstration rules rather than claims about the company's actual accounting policy. The logs prove the repeated Excel/accounting workflow, but they do not expose the complete production formula. The production version would replace the demo rules with the approved company rules.

\---

# 9\. Additional enterprise-style checks

I wanted the prototype to show that the value is not just "multiply two columns."

The pipeline also produces:

* total expense;
* total tax;
* total discount;
* reimbursable vs non-reimbursable spend;
* average, median, minimum and maximum transaction values;
* unique employees;
* departments;
* projects;
* merchants;
* monthly totals;
* category totals;
* currency totals;
* duplicate expense-ID detection;
* potential duplicate detection;
* missing-receipt checks;
* amount-limit checks;
* validation status for every row.

The resulting workbook contains:

* `Summary`
* `Calculated\_Data`
* `Exceptions`
* employee/department/category/project/merchant/payment/currency/month analysis sheets
* `Calculation\_Rules`

This makes the result useful as a review package rather than just another CSV.

\---

# 10\. Testing and validation

I treated testing as part of the prototype rather than something to do at the end.

The program has a built-in self-test and a separate test suite.

The self-test passed:

`Preflight WORKFLOW\_003 automation v2 self-test: PASS (7 assertions)`

The external test suite passed all five tests:

* directory batch processing;
* duplicate/unsupported-currency blocking;
* expected calculations with a multi-sheet workbook;
* idempotent mock submission;
* warning handling.

The final test run completed in 2.168 seconds with:

`Ran 5 tests`

`OK`

I then ran the actual large demonstration inputs.

### Large-file test results

|Input|Rows|Result|Errors|Warnings|
|-|-:|-|-:|-:|
|10,000-row Excel|10,000|READY\_FOR\_APPROVAL|0|0|
|5,000-row CSV|5,000|READY\_FOR\_APPROVAL|0|0|
|10,000-row multi-sheet Excel|10,000|READY\_FOR\_APPROVAL|0|0|
|10,000-row anomaly Excel|9,995 usable rows|BLOCKED|14|5|

There were no batch-level processing failures.

The anomaly dataset was deliberately created with invalid/unsafe conditions. The automation did not silently process those rows; it blocked the batch and reported the exceptions.

This is important because an enterprise automation should not only work on clean input. It should also know when **not** to continue.

\---

# 11\. Approval and submission control

The clean 10,000-row batch was taken through the complete state flow:

`READY\_FOR\_APPROVAL -> APPROVED -> SUBMITTED`

The approval record contains the approver and review reason.

The final mock submission produced:

`MOCK-TXN-307C908D2265EC71`

Running `submit` again returned the same submitted state and transaction identity rather than creating another transaction.

This gives the prototype a basic idempotency guarantee for the mock submission path.

No external accounting system was contacted.

The actual successful test used:

* 10,000 input rows;
* 10,000 valid rows;
* 0 errors;
* 0 warnings;
* 250 employees;
* 8 departments;
* 40 projects;
* 14 merchants.

The calculated reporting total in that demonstration batch was JPY 41,412,341,895.54. That number is only a property of the synthetic demo data and is not a claim about the company's real financial volume.

\---

# 12\. Why I chose a deterministic Python implementation

I considered more sophisticated approaches, including an AI agent and direct desktop/RPA automation.

I chose deterministic Python because the selected workflow has a structured calculation component, and the biggest unknown is the company's actual accounting rules and production integration.

A deterministic implementation gives me:

* predictable calculations;
* easy testing;
* clear validation rules;
* reproducible output;
* easier debugging;
* no dependency on an AI agent runtime;
* no need to reproduce a fragile enterprise UI just to demonstrate the core value.

An RPA layer could eventually be added around the same pipeline if the real accounting system does not expose a usable API.

For this prototype, however, adding direct UI automation would increase the implementation risk without improving the demonstration of the core calculation/validation logic.

\---

# 13\. What remains manual after deployment

The prototype intentionally leaves some work with a human.

The human still needs to:

* review calculated values;
* investigate validation warnings/exceptions;
* confirm that the input data is appropriate;
* approve the batch before submission;
* handle cases that require business judgment;
* approve the final accounting action.

This is deliberate.

The logs do not contain enough information to safely automate business approval decisions, and the prototype should not pretend otherwise.

\---

# 14\. Expected impact

The observed Dataset-B recording contains about 7.7 minutes of activity for the selected workflow across 17 occurrences.

I did not convert that directly into a production savings estimate because the README explicitly warns that waiting times in the test environment are shorter than production.

The more defensible conclusion is:

> The work is repeated across multiple sessions and consistently uses the same expense-calculation spreadsheet. Automating the calculation, validation and preparation stage should reduce repetitive manual spreadsheet manipulation while keeping financial approval with a person.

A production ROI calculation would need actual transaction volume, true processing time, waiting time, exception rate, and labor cost.

The prototype also demonstrates a more general benefit: once the input/output contract and approved calculation rules are known, the same pipeline can process thousands of rows and multiple files without requiring a person to manually repeat the same calculations.

\---

# 15\. Risks I expect in a real rollout

### Incorrect or incomplete business rules

The biggest risk is assuming that the visible Excel operations represent the complete accounting logic.

**Evidence:** the logs show the repeated `expense\_calc` workbook and accounting-system interaction, but not the complete formula or policy.

**Mitigation:** have the accounting/process owner approve the calculation rules before production use, and keep the rules versioned.

### Incorrect source data

Bad or incomplete source data can produce incorrect output.

**Evidence:** the prototype's anomaly dataset demonstrated duplicate IDs, unsupported currencies, missing data and policy exceptions.

**Mitigation:** validate before calculation and block hard failures rather than silently continuing.

### Duplicate submission

Retrying an automation after a timeout can create duplicate accounting transactions if submission is not idempotent.

**Evidence:** this is a natural risk of any automated write operation.

**Mitigation:** deterministic batch identity, idempotent transaction identity, explicit state tracking, and reconciliation before production submission.

### Unauthorized accounting action

Automating a calculation does not mean that the tool should also make the final business decision.

**Evidence:** the logs do not establish approval authority or the full approval policy.

**Mitigation:** retain an explicit human approval gate and authenticate the approver in production.

### Integration and authentication problems

The prototype does not connect to the real accounting system.

**Evidence:** the logs only show desktop interaction with the system; they do not expose a supported production API or authentication mechanism.

**Mitigation:** first establish an approved API/service account or an RPA integration with the system owner, then add monitoring and rollback/reconciliation procedures.

### Sensitive financial information

Expense records can contain employee and financial information.

**Evidence:** the workflow already exposes employee references and accounting-related data.

**Mitigation:** access control, encryption, audit logging, least-privilege service accounts, controlled output locations, and appropriate data-retention policies.

\---

# 16\. Why this is an enterprise-style prototype even though the external submission is mocked

I did not interpret "enterprise level" as "add as many technologies as possible."

For me, the important enterprise properties are the controls around the calculation:

```
large input
    ↓
validation
    ↓
deterministic processing
    ↓
exception handling
    ↓
auditable result
    ↓
human approval
    ↓
controlled submission
    ↓
idempotency
```

The prototype demonstrates those properties without pretending that I have production access to the company's accounting system.

That is important because a prototype that directly writes fictional transactions into an unknown accounting system would look more impressive on the surface, but would make assumptions that the provided logs do not justify.

\---

# 17\. What I would do in a production version

The next phase would keep the same core pipeline but replace the demonstration boundaries.

1. Connect the actual source system or approved input/API.
2. Replace the demonstration calculation rules with the approved accounting policy.
3. Add real authentication and authorization.
4. Replace mock submission with the real accounting API/RPA integration.
5. Add reconciliation between submitted transactions and source records.
6. Add monitoring, retry rules and operational alerts.
7. Add versioned rule management and a formal change-approval process.

The prototype was intentionally stopped before these integrations because they require information and access that are not present in the task data.

\---

# 18\. How I approached the work overall

The project went through several failed approaches before the final pipeline.

I first built a reliable atomic activity layer from the raw operation logs. I then tried heuristic grouping and found that simple proximity/context rules could not handle interruptions, interleaving and repeated processes reliably.

I next tried pairwise machine-learning correlation. The classifier itself looked promising, but reconstruction over-merged activities, which showed me that "same execution" and "contiguous segment boundary" were not the same prediction problem.

I therefore changed the ML target to boundary detection between consecutive activities. After fixing a point-activity ownership issue, the final v6 segmentation model achieved a held-out transition F1 of 0.9434 and boundary F1 of 0.7495 at a ±5 second tolerance on Dataset A. I froze that approach rather than continually changing the segmentation layer.

For process discovery, I compared several representations. A comprehensive ablation showed that semantic evidence was much more useful than activity-type order or structural features on the Dataset A holdout. I therefore froze a semantic-first clustering approach for Dataset B.

I then applied the frozen pipeline to Dataset B, produced 400 non-overlapping segments across 15 sessions, discovered 20 workflow clusters, and added a conservative business-type interpretation layer.

Finally, I selected `WORKFLOW\_003` for the prototype because it offered the best balance between repeatability, clarity and implementation feasibility.

\---

# 19\. Time allocation

The original README describes a seven-day task, but I worked through the task on a very compressed schedule.

My practical allocation was:

### Day 1

* understand the README and dataset structure;
* build and validate `activities.py`;
* inspect raw events and activity reconstruction;
* test initial heuristic grouping.

### Day 2

* evaluate the heuristic failures;
* build and evaluate the first ML correlation approach;
* diagnose over-merging;
* change to boundary-first ML;
* validate and freeze `case\_segment\_ml\_v6.py`;
* compare process-discovery representations.

### Day 3

* apply the frozen pipeline to Dataset B;
* validate `segments.jsonl`;
* perform Task 2 workflow/execution analysis;
* infer human-readable business-process families;
* rank automation candidates;
* build and test the WORKFLOW\_003 prototype.

I chose to spend most of the effort early on getting the segmentation layer defensible because everything downstream depends on it. Once the segmentation and workflow discovery layers were frozen, I prioritized completing a working automation prototype instead of continuing to optimize the unsupervised Dataset-B process labels without ground truth.

\---

# 20\. Final status

At the end of this work:

* Step 1 produced a validated `outputs/segments.jsonl` with 400 non-overlapping segments across 15 sessions.
* Task 2 produced workflow-level analysis for 20 discovered clusters.
* Human-readable process types were inferred only where the evidence supported them.
* The automation candidates were prioritized using both potential value and practical feasibility.
* `WORKFLOW\_003` was selected for the prototype.
* The prototype accepts Excel/CSV data, supports multiple files and multiple worksheets, performs validation/calculation/analytics, creates review artifacts, requires approval, records audit events, and provides an idempotent mock submission.
* The prototype passed its built-in checks, five additional tests, large-file tests, multi-file processing, anomaly handling, approval, and repeat-submission tests.

The most important limitation is that Dataset B has no ground truth and the logs do not expose the complete production accounting rules or integration interface. The prototype therefore demonstrates a reliable automation structure rather than claiming to be a production accounting connector.

