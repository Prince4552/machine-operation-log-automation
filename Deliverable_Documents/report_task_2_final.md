**NAME: Priyanshu Kripashankar Singh**
**Roll No.: BM24BTECH11020**
**Email: bm24btech11020@iith.ac.in**
**IIT Hyderabad - Department of Biomedical Engineering**

# Final Report — Dataset B Analysis and Automation Prototypes

## 1. What I was trying to solve

The main goal of the task was not simply to split a desktop recording into time ranges. I had to recover meaningful units of business work from continuous operation logs, understand what kinds of work people were doing, identify opportunities for automation, and then build working prototypes for some of those opportunities.

For Dataset B, there was no ground truth. That meant I had to be careful not to present inferred process names as facts. I therefore treated the output labels from process discovery as internal workflow IDs and used repeated application, window, document, and activity evidence to infer human-readable process types.

The final Step 1 output is `outputs/segments.jsonl`. Task 2 and both prototypes were built around that frozen output.

## 2. How I moved from Step 1 to Task 2

The final Dataset B result contains:

| Metric | Result |
|---|---:|
| Sessions | 15 |
| Atomic activities | 9,169 |
| Inferred workflow occurrences | 400 |
| Workflow clusters | 20 |
| Recorded segment time | ~176.2 minutes |
| Activities assigned to exactly one segment | 9,169 |
| Activities left unassigned | 0 |
| Segment overlaps | 0 |

I also kept three concepts separate because they mean different things:

**Workflow cluster** — for example, `WORKFLOW_003`. This is an internal cluster ID produced by unsupervised process discovery. It is not the original business-process name.

**Inferred execution occurrence** — for example, `WORKFLOW_003_EXEC_0001`. This is an ID that I generated for one inferred contiguous occurrence. It is not an original case ID or execution ID from the source system.

**Business-process type** — a human-readable interpretation such as "Expense calculation / settlement support", based on recurring evidence in the cluster.

This distinction was important because Dataset B does not give me enough information to claim that a particular segment is "Employee-001 registration" or "Invoice-002 approval" unless that identity is explicitly recoverable from the logs.

## 3. What I found in Dataset B

The 20 discovered workflow clusters were not equally clear.

Some had strong recurring evidence. For example:

- `WORKFLOW_003` repeatedly used an `expense_calc` Excel artifact and the financial-accounting system.
- `WORKFLOW_006` repeatedly used supplier/business-partner and contract procedures together with the financial-accounting system.
- `WORKFLOW_010` repeatedly used a new-hire checklist together with the HR system.
- `WORKFLOW_004` repeatedly used the monthly fixed-amount business-partner list.
- `WORKFLOW_016` repeatedly contained an administrator-permission request procedure.

Other clusters mixed several systems or contained too little distinctive evidence to justify a narrow process name. I kept those clusters generic rather than inventing a business meaning.

The human-readable interpretation of the major clusters was:

| Workflow | Inferred business type | Confidence | Occurrences | Sessions | Recorded time |
|---|---|---|---:|---:|---:|
| `WORKFLOW_006` | Supplier / business-partner / contract administration | High | 64 | 10 | 26.2 min |
| `WORKFLOW_014` | Outsourced-work acceptance / expense administration | High | 43 | 8 | 18.7 min |
| `WORKFLOW_004` | Monthly fixed-amount business-partner list review | High | 43 | 9 | 16.8 min |
| `WORKFLOW_010` | New-hire onboarding / employee joining verification | High | 41 | 9 | 17.8 min |
| `WORKFLOW_007` | HR/order-system administrative review | Low | 32 | 10 | 12.9 min |
| `WORKFLOW_005` | HR-system administrative handling | Low | 26 | 4 | 12.9 min |
| `WORKFLOW_008` | HR-system administrative handling | Low | 22 | 7 | 10.7 min |
| `WORKFLOW_018` | Mixed HR/order/accounting administrative handling | Low | 21 | 2 | 8.9 min |
| `WORKFLOW_003` | Expense calculation / settlement support | High | 17 | 7 | 7.7 min |
| `WORKFLOW_015` | Expense settlement confirmation | High | 15 | 8 | 6.1 min |
| `WORKFLOW_001` | Mixed administrative handling | Low | 13 | 10 | 4.3 min |
| `WORKFLOW_002` | Mixed financial/HR administrative handling | Low | 12 | 9 | 6.7 min |
| `WORKFLOW_013` | Childcare / nursing-care leave administration | High | 11 | 4 | 5.0 min |
| `WORKFLOW_016` | Administrator access / permission request | High | 11 | 4 | 6.9 min |
| `WORKFLOW_009` | Mixed HR/order-system administrative handling | Low | 9 | 7 | 5.3 min |
| `WORKFLOW_011` | Budget analysis / financial planning support | High | 7 | 1 | 2.9 min |
| `WORKFLOW_012` | Financial-accounting administrative handling | Low | 5 | 5 | 3.1 min |
| `WORKFLOW_017` | Mixed administrative handling | Low | 3 | 2 | 1.1 min |
| `WORKFLOW_019` | HR case/comment entry or confirmation | Medium | 3 | 2 | 1.1 min |
| `WORKFLOW_020` | Order/inventory-system administrative handling | Low | 2 | 1 | 1.0 min |

The detailed evidence catalogue is kept separately in `outputs/dataset_b/task2_business/task2_business_workflow_catalog.md`.

The recorded minutes are useful for comparing workflows inside this dataset. I did not treat them as direct production time savings because the README notes that the recordings come from a test environment with shorter waiting times than production.

## 4. How I selected the automation candidates

I did not simply choose the workflows with the largest number of occurrences.

I considered:

1. frequency;
2. recorded time;
3. clarity of the business-work pattern;
4. repeatability;
5. cross-application complexity;
6. amount of human judgment involved;
7. implementation and governance risk;
8. most importantly, whether I could build a credible end-to-end prototype in the time available.

That last point mattered a lot. A very large process is not automatically the right prototype target if reproducing its real system integration would take days. This is also why the work below ended up as **two** prototypes rather than one: the first candidate was the clearest four-hour build, and the second became feasible once I had a controlled, tool-based architecture to split a mixed, multi-procedure workflow into safe individual actions rather than one monolithic script.

## 5. Automation candidates

### 5.1 WORKFLOW_003 — Expense calculation / settlement support

This became my first prototype target.

There were 17 inferred occurrences across 7 sessions and about 7.7 minutes of recorded activity.

The strongest evidence was unusually consistent: the same `expense_calc` Excel artifact appeared in all 17 occurrences. Microsoft Excel appeared in all 17, the financial-accounting system in 12, and Microsoft Edge in 16.

The visible pattern suggested a repeated flow around:

```text
source/accounting information -> Excel calculation -> result preparation -> accounting-system interaction
```

The workflow was therefore a good candidate for automating the repetitive calculation and preparation part while keeping final approval under human control.

**Why I chose it for the first prototype:** it gave me the best balance of a repeated business artifact, a recognizable workflow, structured data, deterministic computation, a relatively small number of core decisions, and a realistic chance of finishing a reliable prototype quickly. It also allowed me to demonstrate a complete automation pipeline without pretending that I had access to the company's real accounting API.

### 5.2 WORKFLOW_010 — New-hire onboarding / employee joining verification

This workflow had 41 occurrences across 9 sessions and about 17.8 recorded minutes.

The strongest evidence was the repeated `nyusha_checklist_shinsotsu_batch` artifact, which appeared in 40 of 41 occurrences, together with the HR system.

This is a strong automation candidate because the work appears to involve repeated movement from a checklist/source document into structured HR-system information.

I did not choose it for a prototype because it involves sensitive employee information, more applications, and HR-specific business rules that are not exposed by the logs. A real end-to-end implementation would therefore need more integration and governance work.

### 5.3 WORKFLOW_004 — Monthly fixed-amount business-partner list review

This workflow had 43 occurrences across 9 sessions and about 16.8 recorded minutes.

The recurring `getsujitsu_teigaku_torihikisaki_ichiran` artifact appeared in 31 occurrences. The workflow repeatedly involved the financial-accounting system, Edge, Word, and supporting systems.

This is naturally suited to report generation, data extraction and validation. I placed it behind the other candidates because the workflow spans many applications and the logs do not expose enough of the underlying business rules to reproduce the complete real process quickly.

## 6. Why I did not choose the largest workflow first

`WORKFLOW_006` had the largest observed workload:

- 64 occurrences;
- 10 sessions;
- about 26.2 recorded minutes.

It looked attractive based on volume alone, but closer inspection showed that the cluster contained several related procedures:

- `shinkuitorihikisaki_touroku_tetsuzuki` (supplier/business-partner registration)
- `shinkui_keiyaku_tetsuzuki` (contract procedures)
- `keiyaku_kaijo_tetsuzuki` (contract termination)

The workflow also involved six applications and substantial application switching.

I therefore treated it as a high-impact area that first needed to be split into smaller, individually controllable procedures rather than automated as one script. That is exactly what I did later: **`WORKFLOW_006` became the basis for a second automation prototype**, described in Section 15 onward, once I had time to build a tool-based (MCP) architecture where each procedure — registration, contract creation/amendment, termination — is a separate, individually validated and approved action rather than one large monolithic pipeline.

The same reasoning applied to `WORKFLOW_014`: it had a high workload, but its evidence covered more than one related work family. Smaller workflows were also excluded when their business meaning was unclear, their session coverage was too narrow, or the likely automation would require an important human authorization decision.

## 7. Step 3 — What I actually built (Prototype 1)

**Chosen workflow: `WORKFLOW_003` — Expense calculation / settlement support**

I deliberately did not try to build an "AI accounting agent" or reproduce the whole accounting system.

Instead, I built a deterministic Python automation pipeline with the following scope:

```text
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
READY_FOR_APPROVAL
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

## 8. What Automation 1 calculates

The prototype uses transparent, configurable calculation rules.

For each expense row:

```text
subtotal          = quantity × unit_amount
discount          = subtotal × discount_rate
taxable_amount    = subtotal − discount
tax               = taxable_amount × tax_rate
calculated_amount = taxable_amount + tax
reporting_amount  = calculated_amount × approved FX rate
```

The output workbook also documents these rules in a separate `Calculation_Rules` sheet.

These are demonstration rules rather than claims about the company's actual accounting policy. The logs prove the repeated Excel/accounting workflow, but they do not expose the complete production formula. The production version would replace the demo rules with the approved company rules.

## 9. Additional enterprise-style checks (Automation 1)

I wanted the prototype to show that the value is not just "multiply two columns."

The pipeline also produces:

- total expense, total tax, total discount;
- reimbursable vs non-reimbursable spend;
- average, median, minimum and maximum transaction values;
- unique employees, departments, projects, merchants;
- monthly totals, category totals, currency totals;
- duplicate expense-ID detection and potential-duplicate detection;
- missing-receipt checks and amount-limit checks;
- validation status for every row.

The resulting workbook contains a `Summary`, `Calculated_Data`, and `Exceptions` sheet, plus employee/department/category/project/merchant/payment/currency/month analysis sheets and a `Calculation_Rules` sheet. This makes the result useful as a review package rather than just another CSV.

## 10. Testing and validation (Automation 1)

I treated testing as part of the prototype rather than something to do at the end.

The program has a built-in self-test and a separate test suite.

The self-test passed: `Preflight WORKFLOW_003 automation v2 self-test: PASS (7 assertions)`.

The external test suite passed all five tests:

- directory batch processing;
- duplicate/unsupported-currency blocking;
- expected calculations with a multi-sheet workbook;
- idempotent mock submission;
- warning handling.

The final test run completed in 2.168 seconds with `Ran 5 tests` / `OK`.

I then ran the actual large demonstration inputs.

### Large-file test results

| Input | Rows | Result | Errors | Warnings |
|---|---:|---|---:|---:|
| 10,000-row Excel | 10,000 | READY_FOR_APPROVAL | 0 | 0 |
| 5,000-row CSV | 5,000 | READY_FOR_APPROVAL | 0 | 0 |
| 10,000-row multi-sheet Excel | 10,000 | READY_FOR_APPROVAL | 0 | 0 |
| 10,000-row anomaly Excel | 9,995 usable rows | BLOCKED | 14 | 5 |

There were no batch-level processing failures.

The anomaly dataset was deliberately created with invalid/unsafe conditions. The automation did not silently process those rows; it blocked the batch and reported the exceptions. This is important because an enterprise automation should not only work on clean input — it should also know when **not** to continue.

## 11. Approval and submission control (Automation 1)

The clean 10,000-row batch was taken through the complete state flow: `READY_FOR_APPROVAL -> APPROVED -> SUBMITTED`.

The approval record contains the approver and review reason.

The final mock submission produced `MOCK-TXN-307C908D2265EC71`. Running `submit` again returned the same submitted state and transaction identity rather than creating another transaction. This gives the prototype a basic idempotency guarantee for the mock submission path. No external accounting system was contacted.

The actual successful test used 10,000 input rows, 10,000 valid rows, 0 errors, 0 warnings, 250 employees, 8 departments, 40 projects, and 14 merchants. The calculated reporting total in that demonstration batch was JPY 41,412,341,895.54. That number is only a property of the synthetic demo data and is not a claim about the company's real financial volume.

## 12. Why I chose a deterministic Python implementation (Automation 1)

I considered more sophisticated approaches, including an AI agent and direct desktop/RPA automation.

I chose deterministic Python because the selected workflow has a structured calculation component, and the biggest unknown is the company's actual accounting rules and production integration.

A deterministic implementation gives me predictable calculations, easy testing, clear validation rules, reproducible output, easier debugging, no dependency on an AI agent runtime, and no need to reproduce a fragile enterprise UI just to demonstrate the core value.

An RPA layer could eventually be added around the same pipeline if the real accounting system does not expose a usable API. For this prototype, however, adding direct UI automation would increase the implementation risk without improving the demonstration of the core calculation/validation logic.

## 13. What remains manual after Automation 1

The prototype intentionally leaves some work with a human, who still needs to:

- review calculated values;
- investigate validation warnings/exceptions;
- confirm that the input data is appropriate;
- approve the batch before submission;
- handle cases that require business judgment;
- approve the final accounting action.

This is deliberate. The logs do not contain enough information to safely automate business approval decisions, and the prototype should not pretend otherwise.

## 14. Expected impact of Automation 1

The observed Dataset-B recording contains about 7.7 minutes of activity for the selected workflow across 17 occurrences.

I did not convert that directly into a production savings estimate because the README explicitly warns that waiting times in the test environment are shorter than production.

The more defensible conclusion is:

> The work is repeated across multiple sessions and consistently uses the same expense-calculation spreadsheet. Automating the calculation, validation and preparation stage should reduce repetitive manual spreadsheet manipulation while keeping financial approval with a person.

A production ROI calculation would need actual transaction volume, true processing time, waiting time, exception rate, and labor cost. The prototype also demonstrates a more general benefit: once the input/output contract and approved calculation rules are known, the same pipeline can process thousands of rows and multiple files without requiring a person to manually repeat the same calculations.

## 15. Step 4 — A second prototype: WORKFLOW_006 (supplier and contract operations)

**Chosen workflow: `WORKFLOW_006` — Supplier / business-partner / contract administration**

Once the first prototype was complete and its pipeline pattern (validate → process → review → approve → submit, with an audit trail at every step) was proven, I went back to the workflow I had deliberately set aside in Section 6.

The reason `WORKFLOW_006` was hard to automate as a single script is exactly why it is well suited to a tool-based approach: it is not one procedure but a family of related ones — supplier registration, contract creation/amendment, and contract termination — each with its own validation rules, risk profile, and approval requirements. Rather than writing one script that tries to guess which procedure applies, I built an **MCP-based operations copilot**: a set of narrow, individually-scoped tools that a controlling model (or a human) can call one at a time, with every state-changing action still validated and gated by the underlying business service rather than by the model itself.

**Location:** `automation_2/`

## 16. What Automation 2 does

The prototype is designed around the following sequence:

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

- searching and retrieving business partners;
- listing and reading contracts;
- checking request completeness;
- finding duplicate suppliers;
- assessing contract requests;
- preparing cases;
- requesting and recording approval;
- submitting approved cases;
- retrieving case status and audit history.

The supported request types map directly onto the procedures found inside `WORKFLOW_006`:

```text
supplier_registration
contract_creation
contract_amendment
contract_termination
```

Critically, the business service — not the language model — handles deterministic validation, policy checks, state changes, and approval enforcement. The model can call tools and prepare cases, but it cannot itself move a case forward without passing through those checks.

The prototype uses vendor-neutral interfaces (`PartnerDirectory`, `ContractSystem`, `DocumentStore`, `WorkflowSystem`, `SignatureProvider`, `AuditStore`), with demo implementations backed by SQLite and mock adapters. This means the same MCP tool contract could later be pointed at real enterprise systems without changing how the tools are called.

The case state machine mirrors the approval discipline used in Automation 1:

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

Hard validation failures enter `BLOCKED`, the same fail-closed pattern used for the expense batches in Automation 1.

## 17. Safety and control points (Automation 2)

Because this prototype lets a model drive a sequence of business actions rather than a single deterministic script, I paid particular attention to making sure an AI call could never become an unrestricted write operation. Controls include:

- duplicate-supplier checks;
- required-field validation;
- enhanced review for large contract-value changes;
- blocking termination when open obligations are reported;
- explicit approval before submission;
- idempotency for repeated submissions;
- fail-closed handling for integration failures;
- least-privilege tool access;
- no credentials stored in source code;
- audit logging.

These are the same underlying principles as the expense prototype's exception blocking and idempotent submission — validate first, prefer blocking to guessing, and never let a single call skip the approval gate.

## 18. Why an MCP-based architecture instead of a single script

For Automation 1, a deterministic script was the right choice: one clear calculation, one input shape, one output shape. `WORKFLOW_006` is different — it is a family of related but distinct procedures, discovered inside one cluster only because they share applications and context, not because they share a calculation.

An MCP architecture let me:

- keep each procedure (registration, contract creation, amendment, termination) as a separately validated action instead of one large branching script;
- keep the policy/risk checks inside the business service, so the model cannot bypass them by phrasing a request differently;
- reuse the same case state machine and approval discipline as Automation 1, so both prototypes are governed the same way even though their entry points differ;
- point the same tool contract at real systems later (via the vendor-neutral interfaces) without redesigning the automation.

The mock adapters and SQLite-backed demo store exist for the same reason Automation 1's submission is mocked: the logs do not expose a supported production API, authentication model, or the company's actual approval policy for supplier and contract changes.

## 19. Testing Automation 2

The prototype ships with its own test suite, `automation_2/tests/`:

- `test_engine_hundreds.py` — exercises the case engine and validation logic at a larger, hundreds-of-records scale, in the same spirit as Automation 1's large-file tests;
- `test_security_and_connectors.py` — covers the safety controls above (duplicate checks, least-privilege access, fail-closed behavior) and the mock connector adapters;
- `test_server_contract.py` — checks that the MCP server's tool contract behaves as declared, so a caller cannot get a different shape of response than the tools advertise.

`generate_demo_data.py` produces reproducible demo suppliers/contracts, `smoke_demo.py` runs an end-to-end smoke path across the state machine, and `verify_mcp_runtime.py` checks that the MCP runtime is correctly wired before the server is used interactively (`mcp dev contract_ops_mcp\mcp_server\server.py`).

## 20. What remains manual after Automation 2

As with Automation 1, the prototype is intentionally not a full self-service system. A human still needs to:

- approve any case before it reaches `SUBMITTED`;
- review cases flagged for enhanced review (large contract-value changes, terminations with open obligations);
- confirm that duplicate-supplier or policy warnings are correctly resolved;
- own the final business decision — the tools prepare and validate a case, they do not decide it.

## 21. Expected impact of Automation 2

`WORKFLOW_006` was the single largest observed workflow in Dataset B, at 64 occurrences across 10 sessions (~26.2 recorded minutes) — larger than the workflow chosen for Automation 1. As with Automation 1, I am not converting that recorded time directly into a production savings figure, for the same reason: the test-environment recording does not reflect true production timing.

The more defensible conclusion is similar in shape to Automation 1's: this cluster represents a repeated family of supplier/contract procedures spread across many sessions. Splitting it into individually validated, individually approved actions — rather than one large script — should reduce repetitive manual lookup, cross-checking, and re-entry across the partner, contract, and document systems, while keeping every state-changing decision behind an explicit human approval gate.

## 22. Risks I expect in a real rollout

### Incorrect or incomplete business rules

The biggest risk, for both prototypes, is assuming that the visible operations represent the complete business logic.

**Evidence:** the logs show the repeated `expense_calc` workbook and accounting-system interaction for Automation 1, and repeated supplier/contract procedures for Automation 2, but not the complete formula or policy behind either.

**Mitigation:** have the relevant process owner (accounting for Automation 1, procurement/legal for Automation 2) approve the rules before production use, and keep the rules versioned.

### Incorrect source data

Bad or incomplete source data can produce incorrect output in either prototype.

**Evidence:** Automation 1's anomaly dataset demonstrated duplicate IDs, unsupported currencies, missing data and policy exceptions; Automation 2's validation and duplicate-supplier checks exist for the same class of problem on the contract/supplier side.

**Mitigation:** validate before processing and block hard failures rather than silently continuing, in both prototypes.

### Duplicate submission

Retrying an automation after a timeout can create duplicate transactions or duplicate cases if submission is not idempotent.

**Evidence:** this is a natural risk of any automated write operation, expense submission or contract-case submission alike.

**Mitigation:** deterministic batch/case identity, idempotent transaction identity, explicit state tracking, and reconciliation before production submission.

### Unauthorized business action

Automating a calculation or a case-preparation step does not mean the tool should also make the final business decision.

**Evidence:** the logs do not establish approval authority or the full approval policy for either expense settlement or supplier/contract changes.

**Mitigation:** retain an explicit human approval gate in both prototypes, and authenticate the approver in production.

### Integration and authentication problems

Neither prototype connects to the real production systems.

**Evidence:** the logs only show desktop interaction with the relevant systems; they do not expose a supported production API or authentication mechanism for accounting, the partner directory, or the contract system.

**Mitigation:** first establish an approved API/service account (or an RPA integration) with the system owner for each system, then add monitoring and rollback/reconciliation procedures.

### Sensitive information

Expense records and supplier/contract records can both contain sensitive information — financial data in one case, business-partner and contractual data in the other.

**Evidence:** both workflows already expose employee references, financial data, or business-partner and contract details in the logs.

**Mitigation:** access control, encryption, audit logging, least-privilege service accounts, controlled output locations, and appropriate data-retention policies for both prototypes.

## 23. Why these are enterprise-style prototypes even though external submission is mocked

I did not interpret "enterprise level" as "add as many technologies as possible."

For me, the important enterprise properties are the controls around the automation, and both prototypes share the same underlying shape:

```text
large input / incoming request
    ↓
validation
    ↓
deterministic processing / policy and risk checks
    ↓
exception handling
    ↓
auditable result / case
    ↓
human approval
    ↓
controlled submission
    ↓
idempotency
```

Automation 1 applies this to a batch of structured expense rows; Automation 2 applies the same shape to an individual supplier or contract request, driven through MCP tools instead of a single script. Both demonstrate these properties without pretending that I have production access to the company's accounting system, partner directory, or contract system.

That is important because a prototype that directly writes fictional transactions or contract changes into an unknown production system would look more impressive on the surface, but would make assumptions that the provided logs do not justify.

## 24. What I would do in a production version

The next phase would keep the same core pipelines but replace the demonstration boundaries.

**For Automation 1 (expense calculation/settlement):**

1. Connect the actual source system or approved input/API.
2. Replace the demonstration calculation rules with the approved accounting policy.
3. Add real authentication and authorization.
4. Replace mock submission with the real accounting API/RPA integration.
5. Add reconciliation between submitted transactions and source records.

**For Automation 2 (supplier and contract operations):**

1. Replace the SQLite/mock adapters behind `PartnerDirectory`, `ContractSystem`, `DocumentStore`, `WorkflowSystem`, `SignatureProvider`, and `AuditStore` with connections to the real systems, without changing the MCP tool contract.
2. Replace the demonstration policy/risk checks with the company's approved procurement and legal policy.
3. Add real authentication, authorization, and role-based approval routing.

**For both:**

1. Add monitoring, retry rules and operational alerts.
2. Add versioned rule/policy management and a formal change-approval process.

Both prototypes were intentionally stopped before these integrations because they require information and access that are not present in the task data.

## 25. How I approached the work overall

The project went through several failed approaches before the final pipeline.

I first built a reliable atomic activity layer from the raw operation logs. I then tried heuristic grouping and found that simple proximity/context rules could not handle interruptions, interleaving and repeated processes reliably.

I next tried pairwise machine-learning correlation. The classifier itself looked promising, but reconstruction over-merged activities, which showed me that "same execution" and "contiguous segment boundary" were not the same prediction problem.

I therefore changed the ML target to boundary detection between consecutive activities. After fixing a point-activity ownership issue, the final v6 segmentation model achieved a held-out transition F1 of 0.9434 and boundary F1 of 0.7495 at a ±5 second tolerance on Dataset A. I froze that approach rather than continually changing the segmentation layer.

For process discovery, I compared several representations. A comprehensive ablation showed that semantic evidence was much more useful than activity-type order or structural features on the Dataset A holdout. I therefore froze a semantic-first clustering approach for Dataset B.

I then applied the frozen pipeline to Dataset B, produced 400 non-overlapping segments across 15 sessions, discovered 20 workflow clusters, and added a conservative business-type interpretation layer.

I selected `WORKFLOW_003` for the first prototype because it offered the best balance between repeatability, clarity and implementation feasibility. Once that pipeline pattern was proven, I returned to `WORKFLOW_006` — the workflow I had set aside as too mixed for a single script — and built a second, MCP-based prototype around it, splitting its supplier-registration, contract, and termination procedures into separately governed actions.

## 26. Time allocation

The original README describes a seven-day task, but I worked through the task on a very compressed schedule.

My practical allocation was:

### Day 1

- understand the README and dataset structure;
- build and validate `activities.py`;
- inspect raw events and activity reconstruction;
- test initial heuristic grouping.

### Day 2

- evaluate the heuristic failures;
- build and evaluate the first ML correlation approach;
- diagnose over-merging;
- change to boundary-first ML;
- validate and freeze `case_segment_ml_v6.py`;
- compare process-discovery representations.

### Day 3

- apply the frozen pipeline to Dataset B;
- validate `segments.jsonl`;
- perform Task 2 workflow/execution analysis;
- infer human-readable business-process families;
- rank automation candidates;
- build and test the `WORKFLOW_003` prototype (Automation 1).

### Day 4

- return to `WORKFLOW_006`, the workflow set aside on Day 3 as too mixed for a single script;
- design the MCP-based tool contract and the vendor-neutral system interfaces;
- implement the case state machine, policy/risk checks, and safety controls;
- build the automation_2 test suite and demo data, and verify the MCP runtime end to end.

I chose to spend most of the early effort getting the segmentation layer defensible because everything downstream depends on it. Once the segmentation and workflow discovery layers were frozen, I prioritized completing a working automation prototype instead of continuing to optimize the unsupervised Dataset-B process labels without ground truth — and once that first prototype was solid, I used the remaining time to bring the second, larger workflow to the same standard rather than leaving it as an unautomated observation.

## 27. Final status

At the end of this work:

- Step 1 produced a validated `outputs/segments.jsonl` with 400 non-overlapping segments across 15 sessions.
- Task 2 produced workflow-level analysis for 20 discovered clusters.
- Human-readable process types were inferred only where the evidence supported them.
- The automation candidates were prioritized using both potential value and practical feasibility.
- `WORKFLOW_003` was selected for the first prototype (Automation 1). It accepts Excel/CSV data, supports multiple files and multiple worksheets, performs validation/calculation/analytics, creates review artifacts, requires approval, records audit events, and provides an idempotent mock submission. It passed its built-in checks, five additional tests, large-file tests, multi-file processing, anomaly handling, approval, and repeat-submission tests.
- `WORKFLOW_006` — the largest workflow in the dataset, and the one deliberately set aside in Section 6 — was selected for a second prototype (Automation 2). It is an MCP-based operations copilot covering supplier registration, contract creation, contract amendment, and contract termination, with the same validate → approve → submit discipline as Automation 1, backed by its own test suite (`test_engine_hundreds.py`, `test_security_and_connectors.py`, `test_server_contract.py`) and a runtime verifier.

The most important limitation is that Dataset B has no ground truth and the logs do not expose the complete production accounting rules, procurement/legal policy, or integration interfaces for either system. Both prototypes therefore demonstrate a reliable automation structure rather than claiming to be production connectors.
