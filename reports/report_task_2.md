# Task 2 — Dataset B Work Analysis and Automation Candidates

## 1\. Objective

Task 2 was to apply the Step 1 segmentation approach to Dataset B and then understand what work was being performed.

The analysis needed to answer:

* What processes are performed?
* How often do they occur?
* How much recorded time do they consume?
* How many people/machines are involved?
* What handling patterns appear within the same process?
* Which processes are reasonable automation candidates, and why?

Dataset B has no ground truth, so the process names below are **evidence-based interpretations**, not confirmed business labels.

The final Step 1 output remains `outputs/segments.jsonl`. Task 2 adds analytical metadata around that file without changing it.

\---

## 2\. Important distinction: cluster, occurrence, and business process

The Step 1/Task 2 pipeline produced three different concepts.

### Workflow cluster

Examples:

`WORKFLOW\_003`, `WORKFLOW\_010`, `WORKFLOW\_014`

These are internal cluster IDs produced by unsupervised process discovery. They are **not** the original business-process names.

### Inferred execution occurrence

For every final contiguous segment, I generated an identifier such as:

`WORKFLOW\_003\_EXEC\_0001`

This is a deterministic ID for one inferred occurrence of that workflow.

It is **not** an original execution ID or case ID from the source system. I use it only so that individual occurrences can be discussed consistently.

### Business-process type

I then inspected repeated evidence across all occurrences in a cluster and inferred human-readable process families such as:

* Expense calculation / settlement support
* New-hire onboarding / employee joining verification
* Administrator access / permission request
* Supplier / business-partner / contract administration

These names are evidence-based interpretations. Dataset B does not provide ground truth for them.

\---

## 3\. Dataset B overview

The final Dataset B output contains:

|Metric|Value|
|-|-:|
|Sessions|15|
|Atomic activities|9,169|
|Inferred workflow occurrences|400|
|Workflow clusters|20|
|Recorded segment time|\~176.2 minutes|
|Activities assigned to exactly one segment|9,169|
|Activities left unassigned|0|
|Overlap in final segments|0|

The activity-to-segment join was corrected so that an activity cannot be counted in two segments. Point activities landing exactly on a shared boundary are assigned deterministically to one side.

The recorded minutes are only measurements from this test dataset. They should be used for relative comparison between workflows, not as a production ROI estimate.

\---

## 4\. Human-readable process interpretation

The following interpretations come from recurring screen/document/application evidence.

|Workflow|Inferred business type|Confidence|Occurrences|Sessions|Recorded time|
|-|-|-|-:|-:|-:|
|WORKFLOW\_006|Supplier / business-partner / contract administration|High|64|10|26.2 min|
|WORKFLOW\_014|Outsourced-work acceptance / expense administration|High|43|8|18.7 min|
|WORKFLOW\_004|Monthly fixed-amount business-partner list review|High|43|9|16.8 min|
|WORKFLOW\_010|New-hire onboarding / employee joining verification|High|41|9|17.8 min|
|WORKFLOW\_007|HR/order-system administrative review|Low|32|10|12.9 min|
|WORKFLOW\_005|HR-system administrative handling|Low|26|4|12.9 min|
|WORKFLOW\_008|HR-system administrative handling|Low|22|7|10.7 min|
|WORKFLOW\_018|Mixed HR/order/accounting administrative handling|Low|21|2|8.9 min|
|WORKFLOW\_003|Expense calculation / settlement support|High|17|7|7.7 min|
|WORKFLOW\_015|Expense settlement confirmation|High|15|8|6.1 min|
|WORKFLOW\_001|Mixed administrative handling|Low|13|10|4.3 min|
|WORKFLOW\_002|Mixed financial/HR administrative handling|Low|12|9|6.7 min|
|WORKFLOW\_013|Childcare / nursing-care leave administration|High|11|4|5.0 min|
|WORKFLOW\_016|Administrator access / permission request|High|11|4|6.9 min|
|WORKFLOW\_009|Mixed HR/order-system administrative handling|Low|9|7|5.3 min|
|WORKFLOW\_011|Budget analysis / financial planning support|High|7|1|2.9 min|
|WORKFLOW\_012|Financial-accounting administrative handling|Low|5|5|3.1 min|
|WORKFLOW\_017|Mixed administrative handling|Low|3|2|1.1 min|
|WORKFLOW\_019|HR case/comment entry or confirmation|Medium|3|2|1.1 min|
|WORKFLOW\_020|Order/inventory-system administrative handling|Low|2|1|1.0 min|

The full evidence catalogue is stored separately in `outputs/dataset\_b/task2\_business/task2\_business\_workflow\_catalog.md`.

\---

# 5\. Automation candidate analysis

I did not rank the candidates using frequency alone.

For the final selection I considered:

1. How often the work occurs.
2. How much recorded time it consumes.
3. How clearly the workflow can be identified from the logs.
4. How repetitive and deterministic the visible work appears.
5. How much cross-application movement is involved.
6. How much business judgment/approval is involved.
7. How risky the workflow would be to automate.
8. Most importantly, whether a credible end-to-end prototype can be built in the remaining \~4 hours.

The last criterion changes the ranking substantially. A large process is not useful as a prototype target if the implementation would require a real production system integration or complicated business rules that cannot be reproduced in the available environment.

\---

# 6\. Ranked top 3 automation candidates

## Rank 1 — WORKFLOW\_003: Expense calculation / settlement support

### Why it is ranked first

This is the cleanest balance between observed value and prototype feasibility.

There are 17 inferred occurrences across 7 sessions and about 7.7 recorded minutes of work.

The most important evidence is that the same `expense\_calc` Excel artifact appears in **all 17 occurrences**.

The application pattern is also concrete:

* Microsoft Excel: 17/17 occurrences
* Financial-accounting system: 12 occurrences
* Microsoft Edge: 16 occurrences

The activity pattern contains Excel interaction, copy operations, text entry, shortcuts and navigation.

### Why it is automatable

The visible work appears to involve a repeated data flow:

`source/accounting information -> Excel calculation -> result preparation -> accounting-system interaction`

That is much easier to reproduce deterministically than a workflow requiring many conditional HR decisions.

A reasonable automation boundary is:

1. collect the required input values;
2. perform the calculation;
3. generate the expected output;
4. prepare the values for system entry;
5. leave the final business approval to a person.

### Why it is feasible 

A deterministic Python prototype can be built without needing to recreate an entire enterprise accounting system.

The prototype can demonstrate:

* structured input,
* calculation,
* validation,
* generated output,
* audit/logging,
* human confirmation before final submission.

This gives a complete end-to-end demonstration while keeping the risky system-write step outside the prototype.

### Remaining manual work

The person should still review the calculated values and approve the final accounting action.

### Main risks

The logs do not prove the exact accounting formulas or all business exceptions. A prototype must therefore avoid pretending that the observed Excel activity is the complete business rule.

A human validation stage is needed before any real system write.

\---

# Rank 2 — WORKFLOW\_010: New-hire onboarding / employee joining verification

### Evidence

This workflow has 41 occurrences across 9 sessions and about 17.8 recorded minutes.

The strongest evidence is:

`nyusha\_checklist\_shinsotsu\_batch`

appearing in **40 of 41 occurrences (97.6%)**.

The workflow repeatedly moves between:

* the onboarding/checklist document,
* the HR system,
* Microsoft Edge,
* Word,
* and a smaller number of other applications.

### Why it is a strong automation candidate

The visible pattern is highly repetitive and has a clear document-to-system structure.

A suitable automation boundary would be:

`checklist / source information -> structured fields -> HR-system entry preparation`

while retaining human HR approval.

### Why it is not Rank 1

The workflow touches more applications and involves sensitive employee information.

The exact HR business rules and validation requirements are not available from the logs.

A genuinely end-to-end production automation would therefore require more integration and governance work than the expense-calculation prototype.

It is still one of the strongest candidates for a later implementation.

\---

# Rank 3 — WORKFLOW\_004: Monthly fixed-amount business-partner list review

### Evidence

This workflow has 43 occurrences across 9 sessions and about 16.8 recorded minutes.

The clearest repeated artifact is:

`getsujitsu\_teigaku\_torihikisaki\_ichiran`

which appears in 31 workflow occurrences.

It repeatedly involves:

* the financial-accounting system,
* Microsoft Edge,
* Word,
* and supporting HR/order-management systems.

### Why it is a strong candidate

A repeated monthly-list operation is naturally suited to report generation, data extraction and validation.

Potential automation:

`accounting system data -> monthly list generation -> validation -> review-ready document`

### Why it is Rank 3 rather than Rank 1

The workflow spans **8 applications** and shows a large number of application switches.

The logs do not tell us enough about the exact business rules behind the list review.

Therefore, a credible prototype would likely need to simulate part of the system integration rather than reproduce the complete real operation.

\---

# 7\. Why WORKFLOW\_006 is not in the top 3

`WORKFLOW\_006` has the largest workload:

* 64 occurrences
* 10 sessions
* about 26.2 recorded minutes

At first glance this looks like the obvious automation target.

However, the evidence shows that the cluster contains several related procedures:

* `shinkuitorihikisaki\_touroku\_tetsuzuki`
* `shinkui\_keiyaku\_tetsuzuki`
* `keiyaku\_kaijo\_tetsuzuki`

These correspond to different business-partner/contract procedures.

The workflow also touches six applications and has a very high application-switch count.

Therefore, I would treat it as a **high-impact future automation area**, but not the safest 4-hour prototype target. Its scope should first be decomposed into smaller procedures.

\---

# 8\. Why WORKFLOW\_014 is not in the top 3

`WORKFLOW\_014` has:

* 43 occurrences
* 8 sessions
* 18.7 recorded minutes

The problem is that the evidence is split between different work families.

One evidence family relates to outsourced-work acceptance/expense procedures, while another relates to representation/entertainment expenses.

The cluster also uses six applications.

This means the cluster is valuable for further automation analysis, but it is not a clean enough single process to prototype quickly without first splitting its scope.

\---

# 9\. Why WORKFLOW\_015 is not in the top 3

`WORKFLOW\_015` is relatively clear:

* 15 occurrences
* 8 sessions
* 6.1 recorded minutes
* `精算確認メモ` in 12 occurrences.

The workflow therefore appears to have a repeatable expense-settlement confirmation component.

However, its observed workload is significantly smaller than the top three, and the evidence still includes several surrounding administrative activities.

It is a reasonable small automation candidate, but not the first process to build under a four-hour constraint.

\---

# 10\. Why WORKFLOW\_016 is not in the top 3

`WORKFLOW\_016` contains the administrator-permission application procedure in 10 of 11 occurrences.

This makes the process identifiable and repetitive.

However, authorization is inherently important here.

The useful automation boundary is therefore limited to:

* request intake,
* routing,
* status updates,
* preparation.

The actual authorization decision should remain human-controlled.

Because the automation boundary is narrower and the workflow has only 11 occurrences, I did not place it in the top three.

\---

# 11\. Why WORKFLOW\_013 is not in the top 3

`WORKFLOW\_013` contains strong evidence for childcare/nursing-care leave administration.

The evidence is clear, but this is an HR eligibility/leave process involving potentially sensitive employee information.

The automation opportunity is mainly document/checklist preparation and status entry.

Actual eligibility decisions should remain with HR.

Its observed volume is also only 11 occurrences across 4 sessions, so it is less attractive for the first prototype.

\---

# 12\. Why WORKFLOW\_011 is not in the top 3

`WORKFLOW\_011` is actually very clean from an evidence perspective.

`budget\_analysis` appears in all 7 occurrences.

The problem is scale:

* 7 occurrences
* only 1 session
* about 2.9 recorded minutes

It looks highly repetitive, but the dataset does not demonstrate that it is a broadly repeated activity across multiple operators/sessions.

I would keep it as a potential later spreadsheet-automation target.

\---

# 13\. Why the low-confidence workflows are not automation targets

The remaining clusters generally have one or more of these problems:

* no distinctive repeated business document or UI cue;
* mixed applications and unrelated administrative activity;
* very low occurrence count;
* very limited session coverage;
* evidence insufficient to assign a reliable business-process type.

For example, `WORKFLOW\_007` has 32 occurrences but mixes order/inventory, HR, accounting and multiple Notepad notes without one dominant business procedure.

`WORKFLOW\_018` has 21 occurrences but only 2 sessions and similarly mixed application evidence.

`WORKFLOW\_019` has only 3 occurrences and its strongest process cue occurs in only one occurrence.

`WORKFLOW\_020` has only 2 occurrences in a single session.

These are not good targets for a prototype because I would be automating something I cannot confidently define.

\---

# 14\. Final prototype choice

## Selected process: WORKFLOW\_003 — Expense calculation / settlement support

This is the process I will target for Step 3.

### Why this process

It has the clearest combination of:

* repeated occurrence,
* consistent business artifact,
* clear application pattern,
* relatively deterministic visible actions,
* understandable input/output structure,
* and a prototype that can be completed without requiring a full enterprise-system integration.

The strongest evidence is the repeated `expense\_calc` Excel artifact in all 17 occurrences, together with repeated Excel/accounting-system interaction.

### Chosen scope

I will **not** attempt to recreate the full enterprise expense/accounting system.

The prototype scope will be:

`input transaction/expense data -> perform calculation -> validate -> produce system-ready result -> human confirmation`

This is intentionally narrower than a production implementation.

### Why a deterministic script

A deterministic Python implementation is preferable for this short prototype because:

* the visible calculation appears structured;
* deterministic calculations are easier to test;
* there is less debugging uncertainty than an AI agent;
* no external agent infrastructure is required;
* the core logic can be demonstrated end-to-end quickly.

An RPA implementation would eventually be useful for direct UI interaction, but reproducing the enterprise application interaction reliably is not realistic within the remaining time.

### What I am deliberately deferring

I am deferring:

* direct production-system writes,
* authentication,
* enterprise API integration,
* approval routing,
* complete exception handling,
* and deployment/governance infrastructure.

The prototype will demonstrate the core automation mechanism and the human-review boundary instead.

\---

# 15\. Expected impact

The Dataset B recordings show about 7.7 minutes of observed time for this workflow across 17 occurrences.

Because the README states that the test environment has shorter waiting time than production, I will **not extrapolate these minutes directly to production savings**.

Instead, the evidence supports a more conservative claim:

> The workflow is repeated across seven sessions and uses a highly consistent spreadsheet artifact. Automating the calculation and preparation portion should reduce repetitive manual manipulation while leaving business validation and final approval to the user.

A production ROI estimate would require real transaction volume, actual waiting time, exception frequency, and average employee cost.

\---

# 16\. Overall Task-2 conclusion

Dataset B contains 20 discovered workflow clusters and 400 inferred occurrences across 15 sessions.

The clustering does not provide ground-truth business names, so I used repeated semantic/UI evidence to assign human-readable process families only where the evidence was sufficiently strong.

The strongest automation opportunities are not necessarily the largest clusters. The largest cluster, `WORKFLOW\_006`, has the largest observed workload but also contains several different contract/business-partner procedures and a complicated cross-application footprint.

The first prototype should therefore focus on `WORKFLOW\_003` because it combines a clear repeated artifact, a relatively deterministic calculation pattern, multiple observed repetitions, and a realistic implementation scope for the remaining development time.

The final selection is therefore:

1. **WORKFLOW\_003 — Expense calculation / settlement support**
2. **WORKFLOW\_010 — New-hire onboarding / employee joining verification**
3. **WORKFLOW\_004 — Monthly fixed-amount business-partner list review**

The prototype implementation is intentionally scoped to the part of the selected workflow that can be demonstrated reliably in the remaining time.

