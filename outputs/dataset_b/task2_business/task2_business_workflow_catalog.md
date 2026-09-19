# Dataset B — Business Workflow Catalogue

## Purpose

This is the human-readable Task-2 interpretation of the 20 workflow clusters
discovered from Dataset B. `WORKFLOW_*` is an internal cluster ID; it is not the
real business-process name. The names below are evidence-based interpretations.
Because Dataset B has no ground truth, confidence is intentionally shown and
ambiguous clusters are not forced into a precise business label.

- Workflow clusters: **20**
- Inferred workflow occurrences: **400**
- Recorded segment time: **176.2 min**

## Whole-dataset summary

| Workflow | Inferred business type | Confidence | Occurrences | Sessions | Recorded time | Apps | Entity values |
|---|---|---|---:|---:|---:|---:|---:|
| WORKFLOW_006 | Supplier / business-partner / contract administration | high | 64 | 10 | 26.2 min | 6 | 0 |
| WORKFLOW_004 | Monthly fixed-amount business-partner list review | high | 43 | 9 | 16.8 min | 8 | 6 |
| WORKFLOW_014 | Outsourced-work acceptance / expense administration | high | 43 | 8 | 18.7 min | 6 | 0 |
| WORKFLOW_010 | New-hire onboarding / employee joining verification | high | 41 | 9 | 17.8 min | 7 | 0 |
| WORKFLOW_007 | HR-system record review / administrative handling | low | 32 | 10 | 12.9 min | 6 | 3 |
| WORKFLOW_005 | HR-system record review / administrative handling | low | 26 | 4 | 12.9 min | 7 | 12 |
| WORKFLOW_008 | HR-system record review / administrative handling | low | 22 | 7 | 10.7 min | 4 | 0 |
| WORKFLOW_018 | HR-system record review / administrative handling | low | 21 | 2 | 8.9 min | 6 | 0 |
| WORKFLOW_003 | Expense calculation / settlement support | high | 17 | 7 | 7.7 min | 7 | 17 |
| WORKFLOW_015 | Expense settlement confirmation | high | 15 | 8 | 6.1 min | 6 | 0 |
| WORKFLOW_001 | HR-system record review / administrative handling | low | 13 | 10 | 4.3 min | 6 | 3 |
| WORKFLOW_002 | HR-system record review / administrative handling | low | 12 | 9 | 6.7 min | 7 | 0 |
| WORKFLOW_013 | Childcare / nursing-care leave administration | high | 11 | 4 | 5.0 min | 4 | 0 |
| WORKFLOW_016 | Administrator access / permission request | high | 11 | 4 | 6.9 min | 8 | 2 |
| WORKFLOW_009 | HR-system record review / administrative handling | low | 9 | 7 | 5.3 min | 6 | 0 |
| WORKFLOW_011 | Budget analysis / financial planning support | high | 7 | 1 | 2.9 min | 4 | 16 |
| WORKFLOW_012 | Financial-accounting record review / administrative handling | low | 5 | 5 | 3.1 min | 3 | 1 |
| WORKFLOW_017 | HR-system record review / administrative handling | low | 3 | 2 | 1.1 min | 6 | 0 |
| WORKFLOW_019 | HR case/comment entry or confirmation | medium | 3 | 2 | 1.1 min | 4 | 0 |
| WORKFLOW_020 | Order/inventory-system record review / administrative handling | low | 2 | 1 | 1.0 min | 2 | 0 |

## Detailed workflow interpretation

### WORKFLOW_006 — Supplier / business-partner / contract administration

**Confidence:** high

**Observed volume:** 64 inferred occurrences across 10 sessions.

**Recorded time:** 26.2 minutes.

**Application footprint:** 6 distinct applications, 1169 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Supplier / business-partner / contract administration — matched 98 evidence occurrences across 60 workflow occurrences (93.8% coverage).
  - Cues: `shinkui_keiyaku_tetsuzuki` × 32, `keiyaku_kaijo_tetsuzuki` × 35, `shinkuitorihikisaki_touroku_tetsuzuki` × 31
  - New business-partner registration and contract/cancellation procedure documents recur throughout the workflow.

**Dominant application cues:**
- `Microsoft Edge` (62 occurrences)
- `browser:受発注在庫管理システム` (44 occurrences)
- `Microsoft Word` (35 occurrences)
- `browser:財務会計システム` (18 occurrences)
- `browser:HR人事給与システム` (4 occurrences)
- `prl_cc` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 579
- `APP_SWITCH`: 324
- `SCROLL`: 164
- `COPY`: 130
- `SHORTCUT`: 89
- `NAVIGATE`: 17
- `TEXT_ENTRY`: 4
- `OTHER`: 3

**Representative evidence:**
- `browser_tab=受発注在庫管理システム`
- `window=受発注在庫管理システム - Profile 1 - Microsoft​ Edge`
- `text=ctrl+end`
- `window=keiyaku_kaijo_tetsuzuki - Compatibility Mode - Word`
- `text=ctrl+s`
- `window=shinkuitorihikisaki_touroku_tetsuzuki - Compatibility Mode - Word`
- `text=alt+f4`
- `window=shinkui_keiyaku_tetsuzuki - Compatibility Mode - Word`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `browser_tab=財務会計システム`
- `window=受発注在庫管理システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=keiyaku_kaijo_tetsuzuki [Compatibility Mode] - Word`

**Automation interpretation:** Partial automation candidate: document preparation and cross-system data transfer; retain business decisions.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_004 — Monthly fixed-amount business-partner list review

**Confidence:** high

**Observed volume:** 43 inferred occurrences across 9 sessions.

**Recorded time:** 16.8 minutes.

**Application footprint:** 8 distinct applications, 840 observed application switches.

**Entity evidence:** 6 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Monthly fixed-amount business-partner list review — matched 31 evidence occurrences across 31 workflow occurrences (72.1% coverage).
  - Cues: `getsujitsu_teigaku_torihikisaki_ichiran` × 31
  - A distinctive monthly fixed-amount business-partner list document recurs.

**Dominant application cues:**
- `Microsoft Edge` (43 occurrences)
- `browser:財務会計システム` (37 occurrences)
- `browser:HR人事給与システム` (9 occurrences)
- `OpenWith` (8 occurrences)
- `Microsoft Word` (4 occurrences)
- `browser:受発注在庫管理システム` (3 occurrences)
- `Windows Explorer` (2 occurrences)
- `Notepad` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 415
- `APP_SWITCH`: 136
- `SCROLL`: 110
- `COPY`: 70
- `SHORTCUT`: 19
- `NAVIGATE`: 13
- `TEXT_ENTRY`: 12
- `OTHER`: 1

**Representative evidence:**
- `browser_tab=財務会計システム`
- `window=getsujitsu_teigaku_torihikisaki_ichiran - Compatibility Mode - Word`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `window=財務会計システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `browser_tab=HR人事給与システム`
- `window=財務会計システム and 2 more pages - Profile 1 - Microsoft​ Edge`
- `text=alt+f4`
- `text=ctrl+end`
- `target_field=name=Just once control_type=Button class_name=Button automation_id=OpenWith_OnceButton`
- `window=getsujitsu_teigaku_torihikisaki_ichiran [Compatibility Mode] - Word`
- `text=ctrl+s`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`

**Automation interpretation:** Potential support automation; inspect concrete steps before implementation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_014 — Outsourced-work acceptance / expense administration

**Confidence:** high

**Observed volume:** 43 inferred occurrences across 8 sessions.

**Recorded time:** 18.7 minutes.

**Application footprint:** 6 distinct applications, 765 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Outsourced-work acceptance / expense administration — matched 24 evidence occurrences across 24 workflow occurrences (55.8% coverage).
  - Cues: `gyomu_itaku_ukeire_tetsuzuki` × 11, `gyomu_itaku_keihi_kitei` × 13
  - Outsourced-work acceptance and outsourced-work expense documents recur.
- Representation / entertainment-expense administration — matched 12 evidence occurrences across 12 workflow occurrences (27.9% coverage).
  - Cues: `settai_keihi_kitei` × 12
  - The representation/entertainment-expense policy document recurs in the workflow.

**Dominant application cues:**
- `Microsoft Edge` (40 occurrences)
- `Microsoft Word` (37 occurrences)
- `browser:財務会計システム` (35 occurrences)
- `browser:HR人事給与システム` (8 occurrences)
- `browser:受発注在庫管理システム` (2 occurrences)
- `WindowsTerminal` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 376
- `APP_SWITCH`: 234
- `SCROLL`: 124
- `SHORTCUT`: 115
- `COPY`: 101
- `NAVIGATE`: 13
- `OTHER`: 5
- `TEXT_ENTRY`: 4

**Representative evidence:**
- `text=ctrl+end`
- `text=ctrl+s`
- `browser_tab=財務会計システム`
- `text=alt+f4`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `window=gyomu_itaku_kyuuyo_kitei - Compatibility Mode - Word`
- `window=gyomu_itaku_keihi_kitei - Compatibility Mode - Word`
- `window=settai_keihi_kitei - Compatibility Mode - Word`
- `browser_tab=HR人事給与システム`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `window=gyomu_itaku_ukeire_tetsuzuki - Compatibility Mode - Word`
- `window=財務会計システム and 1 more page - Profile 1 - Microsoft​ Edge`

**Automation interpretation:** Candidate for data collection, calculation and cross-system entry automation; retain approval.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_010 — New-hire onboarding / employee joining verification

**Confidence:** high

**Observed volume:** 41 inferred occurrences across 9 sessions.

**Recorded time:** 17.8 minutes.

**Application footprint:** 7 distinct applications, 637 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- New-hire onboarding / employee joining verification — matched 40 evidence occurrences across 40 workflow occurrences (97.6% coverage).
  - Cues: `nyusha_checklist_shinsotsu_batch` × 40
  - The new-graduate/new-joiner checklist document is repeatedly observed with the HR system.
- Outsourced-work acceptance / expense administration — matched 12 evidence occurrences across 11 workflow occurrences (26.8% coverage).
  - Cues: `gyomu_itaku_ukeire_tetsuzuki` × 6, `gyomu_itaku_keihi_kitei` × 6
  - Outsourced-work acceptance and outsourced-work expense documents recur.

**Dominant application cues:**
- `Microsoft Edge` (41 occurrences)
- `browser:HR人事給与システム` (33 occurrences)
- `Microsoft Word` (27 occurrences)
- `browser:財務会計システム` (6 occurrences)
- `browser:受発注在庫管理システム` (2 occurrences)
- `procmine-desktop-agent` (1 occurrences)
- `Notepad` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 330
- `APP_SWITCH`: 263
- `SCROLL`: 88
- `COPY`: 84
- `SHORTCUT`: 81
- `NAVIGATE`: 13
- `TEXT_ENTRY`: 7
- `OTHER`: 6

**Representative evidence:**
- `window=nyusha_checklist_shinsotsu_batch - Compatibility Mode - Word`
- `browser_tab=HR人事給与システム`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `text=ctrl+end`
- `text=ctrl+s`
- `text=alt+f4`
- `window=Resume Reading`
- `window=HR人事給与システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `text=v`
- `window=gyomu_itaku_keihi_kitei - Compatibility Mode - Word`
- `target_field=name=nyusha_checklist_shinsotsu_batch - Compatibility Mode control_type=Document class_name=_WwG`
- `window=HR人事給与システム and 2 more pages - Profile 1 - Microsoft​ Edge`

**Automation interpretation:** Good candidate for checklist/data-transfer automation; retain human HR approval.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_007 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 32 inferred occurrences across 10 sessions.

**Recorded time:** 12.9 minutes.

**Application footprint:** 6 distinct applications, 746 observed application switches.

**Entity evidence:** 3 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `Microsoft Edge` (31 occurrences)
- `browser:受発注在庫管理システム` (30 occurrences)
- `Notepad` (14 occurrences)
- `browser:HR人事給与システム` (4 occurrences)
- `OpenWith` (2 occurrences)
- `browser:財務会計システム` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 375
- `SCROLL`: 125
- `COPY`: 96
- `APP_SWITCH`: 80
- `NAVIGATE`: 16
- `OTHER`: 7
- `SHORTCUT`: 3
- `TEXT_ENTRY`: 2

**Representative evidence:**
- `browser_tab=受発注在庫管理システム`
- `window=受発注在庫管理システム - Profile 1 - Microsoft​ Edge`
- `window=受発注在庫管理システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=*在庫調整メモ - Notepad`
- `window=*IT申請メモ - Notepad`
- `window=*精算確認メモ - Notepad`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `browser_tab=HR人事給与システム`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `window=Untitled - Notepad`
- `window=HR人事給与システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `browser_tab=財務会計システム`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_005 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 26 inferred occurrences across 4 sessions.

**Recorded time:** 12.9 minutes.

**Application footprint:** 7 distinct applications, 799 observed application switches.

**Entity evidence:** 12 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `Microsoft Edge` (26 occurrences)
- `browser:HR人事給与システム` (17 occurrences)
- `browser:財務会計システム` (10 occurrences)
- `OpenWith` (6 occurrences)
- `browser:受発注在庫管理システム` (2 occurrences)
- `Microsoft Word` (1 occurrences)
- `procmine-desktop-agent` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 395
- `SCROLL`: 147
- `COPY`: 72
- `APP_SWITCH`: 47
- `SHORTCUT`: 17
- `TEXT_ENTRY`: 10
- `NAVIGATE`: 9
- `OTHER`: 5

**Representative evidence:**
- `window=HR人事給与システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `browser_tab=HR人事給与システム`
- `window=財務会計システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `browser_tab=財務会計システム`
- `text=ctrl+s`
- `text=ctrl+end`
- `target_field=name=Just once control_type=Button class_name=Button automation_id=OpenWith_OnceButton`
- `text=alt+f4`
- `window=gyomu_itaku_keihi_kitei - Compatibility Mode - Word`
- `window=gyomu_itaku_ukeire_tetsuzuki - Compatibility Mode - Word`
- `target_field=name=Excel control_type=ListItem class_name=ListViewItem`
- `browser_tab=受発注在庫管理システム`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_008 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 22 inferred occurrences across 7 sessions.

**Recorded time:** 10.7 minutes.

**Application footprint:** 4 distinct applications, 570 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `Microsoft Edge` (22 occurrences)
- `browser:HR人事給与システム` (15 occurrences)
- `browser:財務会計システム` (1 occurrences)
- `prl_cc` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 329
- `SCROLL`: 155
- `COPY`: 67
- `APP_SWITCH`: 17
- `NAVIGATE`: 5

**Representative evidence:**
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `browser_tab=HR人事給与システム`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `window=Untitled - Notepad`
- `browser_tab=財務会計システム`
- `window=受発注在庫管理システム - Profile 1 - Microsoft​ Edge`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_018 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 21 inferred occurrences across 2 sessions.

**Recorded time:** 8.9 minutes.

**Application footprint:** 6 distinct applications, 571 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `Microsoft Edge` (21 occurrences)
- `browser:HR人事給与システム` (12 occurrences)
- `browser:受発注在庫管理システム` (7 occurrences)
- `browser:財務会計システム` (7 occurrences)
- `Notepad` (4 occurrences)
- `Microsoft Word` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 282
- `SCROLL`: 91
- `COPY`: 55
- `APP_SWITCH`: 30
- `NAVIGATE`: 8
- `OTHER`: 4

**Representative evidence:**
- `browser_tab=HR人事給与システム`
- `window=HR人事給与システム and 2 more pages - Profile 1 - Microsoft​ Edge`
- `window=財務会計システム and 2 more pages - Profile 1 - Microsoft​ Edge`
- `browser_tab=受発注在庫管理システム`
- `browser_tab=財務会計システム`
- `window=受発注在庫管理システム and 2 more pages - Profile 1 - Microsoft​ Edge`
- `window=*在庫調整メモ - Notepad`
- `window=gyomu_itaku_keihi_kitei - Compatibility Mode - Word`
- `window=ProcMine Agent`
- `window=*精算確認メモ - Notepad`
- `window=Windows PowerShell`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_003 — Expense calculation / settlement support

**Confidence:** high

**Observed volume:** 17 inferred occurrences across 7 sessions.

**Recorded time:** 7.7 minutes.

**Application footprint:** 7 distinct applications, 225 observed application switches.

**Entity evidence:** 17 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Expense calculation / settlement support — matched 17 evidence occurrences across 17 workflow occurrences (100.0% coverage).
  - Cues: `expense_calc` × 17
  - The expense-calculation spreadsheet is present throughout the workflow occurrences.

**Dominant application cues:**
- `Microsoft Excel` (17 occurrences)
- `Microsoft Edge` (16 occurrences)
- `browser:財務会計システム` (12 occurrences)
- `prl_cc` (1 occurrences)
- `Notepad` (1 occurrences)
- `Microsoft Word` (1 occurrences)
- `browser:受発注在庫管理システム` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 109
- `APP_SWITCH`: 85
- `SCROLL`: 57
- `SHORTCUT`: 54
- `TEXT_ENTRY`: 30
- `COPY`: 20

**Representative evidence:**
- `window=expense_calc - Excel`
- `text=ctrl+end`
- `window=Opening - Excel`
- `browser_tab=財務会計システム`
- `target_field=control_type=Pane class_name=EXCEL6`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `text=ctrl+s`
- `window=財務会計システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `target_field=name=J6 control_type=DataItem class_name=XLSpreadsheetCell automation_id=J6`
- `window=財務会計システム and 2 more pages - Profile 1 - Microsoft​ Edge`
- `text=alt+f4`
- `text==`

**Automation interpretation:** Candidate for data collection, calculation and cross-system entry automation; retain approval.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_015 — Expense settlement confirmation

**Confidence:** high

**Observed volume:** 15 inferred occurrences across 8 sessions.

**Recorded time:** 6.1 minutes.

**Application footprint:** 6 distinct applications, 257 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Expense settlement confirmation — matched 12 evidence occurrences across 12 workflow occurrences (80.0% coverage).
  - Cues: `精算確認メモ` × 12
  - Settlement-confirmation notes recur across the workflow occurrences.

**Dominant application cues:**
- `browser:HR人事給与システム` (14 occurrences)
- `Microsoft Edge` (13 occurrences)
- `Notepad` (12 occurrences)
- `browser:財務会計システム` (2 occurrences)
- `Microsoft Word` (1 occurrences)
- `browser:受発注在庫管理システム` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 144
- `SCROLL`: 60
- `APP_SWITCH`: 47
- `COPY`: 46
- `OTHER`: 9
- `NAVIGATE`: 8

**Representative evidence:**
- `browser_tab=HR人事給与システム`
- `window=*精算確認メモ - Notepad`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `window=HR人事給与システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=*在庫調整メモ - Notepad`
- `window=Untitled - Notepad`
- `browser_tab=財務会計システム`
- `window=gyomu_itaku_keihi_kitei - Compatibility Mode - Word`
- `window=財務会計システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=Untitled - Profile 1 - Microsoft​ Edge`
- `window=Settings | Microsoft Teams`
- `browser_tab=受発注在庫管理システム`

**Automation interpretation:** Candidate for data collection, calculation and cross-system entry automation; retain approval.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_001 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 13 inferred occurrences across 10 sessions.

**Recorded time:** 4.3 minutes.

**Application footprint:** 6 distinct applications, 139 observed application switches.

**Entity evidence:** 3 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `Microsoft Edge` (13 occurrences)
- `browser:受発注在庫管理システム` (12 occurrences)
- `browser:HR人事給与システム` (10 occurrences)
- `browser:財務会計システム` (10 occurrences)
- `WindowsTerminal` (4 occurrences)
- `procmine-desktop-agent` (1 occurrences)

**Dominant activity types:**
- `APP_SWITCH`: 132
- `OTHER`: 66
- `NAVIGATE`: 40
- `CLICK`: 38
- `SCROLL`: 6
- `TEXT_ENTRY`: 3
- `COPY`: 2

**Representative evidence:**
- `browser_tab=受発注在庫管理システム`
- `window=Turn off extensions in developer mode`
- `browser_tab=財務会計システム`
- `browser_tab=HR人事給与システム`
- `window=受発注在庫管理システム - Profile 1 - Microsoft​ Edge`
- `window=Notepad`
- `window=Windows PowerShell`
- `window=受発注在庫管理システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=Untitled - Profile 1 - Microsoft​ Edge`
- `window=Chat | Microsoft Teams`
- `window=Microsoft Teams`
- `window=Untitled and 1 more page - Profile 1 - Microsoft​ Edge`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_002 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 12 inferred occurrences across 9 sessions.

**Recorded time:** 6.7 minutes.

**Application footprint:** 7 distinct applications, 240 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `browser:財務会計システム` (11 occurrences)
- `Microsoft Edge` (10 occurrences)
- `WindowsTerminal` (10 occurrences)
- `browser:HR人事給与システム` (8 occurrences)
- `procmine-desktop-agent` (7 occurrences)
- `browser:受発注在庫管理システム` (7 occurrences)
- `prl_cc` (1 occurrences)

**Dominant activity types:**
- `SCROLL`: 408
- `CLICK`: 107
- `APP_SWITCH`: 47
- `OTHER`: 37
- `NAVIGATE`: 28
- `COPY`: 14

**Representative evidence:**
- `browser_tab=財務会計システム`
- `window=Windows PowerShell`
- `window=ProcMine Agent`
- `browser_tab=HR人事給与システム`
- `browser_tab=受発注在庫管理システム`
- `window=財務会計システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `window=財務会計システム and 2 more pages - Profile 1 - Microsoft​ Edge`
- `window=getsujitsu_teigaku_torihikisaki_ichiran - Compatibility Mode - Word`
- `window=Turn off extensions in developer mode`
- `window=Opening - Word`
- `window=getsujitsu_teigaku_torihikisaki_ichiran [Compatibility Mode] - Word`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_013 — Childcare / nursing-care leave administration

**Confidence:** high

**Observed volume:** 11 inferred occurrences across 4 sessions.

**Recorded time:** 5.0 minutes.

**Application footprint:** 4 distinct applications, 309 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Childcare / nursing-care leave administration — matched 10 evidence occurrences across 9 workflow occurrences (81.8% coverage).
  - Cues: `ikuji_kyuugyou_kitei` × 9, `kaigo_kyuugyou_kitei` × 1
  - Distinctive childcare/nursing-care leave procedure documents recur with the HR system.

**Dominant application cues:**
- `Microsoft Edge` (11 occurrences)
- `browser:HR人事給与システム` (11 occurrences)
- `Notepad` (1 occurrences)
- `Microsoft Word` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 154
- `APP_SWITCH`: 43
- `SCROLL`: 41
- `COPY`: 26
- `NAVIGATE`: 3

**Representative evidence:**
- `browser_tab=HR人事給与システム`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `window=ikuji_kyuugyou_kitei - Compatibility Mode - Word`
- `window=HR人事給与システム and 2 more pages - Profile 1 - Microsoft​ Edge`
- `window=kazoku_teate_kitei - Compatibility Mode - Word`
- `window=Untitled - Notepad`
- `window=ikuji_kyuugyou_kitei [Compatibility Mode] - Word`
- `window=kazoku_teate_kitei [Compatibility Mode] - Word`
- `window=shinkuitorihikisaki_touroku_tetsuzuki - Compatibility Mode - Word`
- `window=Opening - Word`
- `window=kaigo_kyuugyou_kitei - Compatibility Mode - Word`
- `window=shinkui_keiyaku_tetsuzuki - Compatibility Mode - Word`

**Automation interpretation:** Candidate for document/checklist preparation and status-entry automation; retain eligibility decisions.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_016 — Administrator access / permission request

**Confidence:** high

**Observed volume:** 11 inferred occurrences across 4 sessions.

**Recorded time:** 6.9 minutes.

**Application footprint:** 8 distinct applications, 368 observed application switches.

**Entity evidence:** 2 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Administrator access / permission request — matched 10 evidence occurrences across 10 workflow occurrences (90.9% coverage).
  - Cues: `kanrisya_kengen_shinsei_tetsuzuki` × 10
  - The administrator-permission application procedure is repeatedly observed.
- IT request / software-license administration — matched 5 evidence occurrences across 5 workflow occurrences (45.5% coverage).
  - Cues: `IT申請メモ` × 5
  - The workflow repeatedly contains an IT-request memo or explicit software-license request.

**Dominant application cues:**
- `Microsoft Edge` (11 occurrences)
- `browser:受発注在庫管理システム` (8 occurrences)
- `Notepad` (5 occurrences)
- `browser:HR人事給与システム` (4 occurrences)
- `browser:財務会計システム` (4 occurrences)
- `Microsoft Word` (2 occurrences)
- `OpenWith` (2 occurrences)
- `procmine-desktop-agent` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 170
- `APP_SWITCH`: 66
- `SCROLL`: 51
- `COPY`: 38
- `NAVIGATE`: 14
- `OTHER`: 8
- `SHORTCUT`: 6
- `TEXT_ENTRY`: 5

**Representative evidence:**
- `window=kanrisya_kengen_shinsei_tetsuzuki - Compatibility Mode - Word`
- `browser_tab=受発注在庫管理システム`
- `window=受発注在庫管理システム - Profile 1 - Microsoft​ Edge`
- `window=*IT申請メモ - Notepad`
- `browser_tab=HR人事給与システム`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `window=gyomu_itaku_keihi_kitei - Compatibility Mode - Word`
- `window=*精算確認メモ - Notepad`
- `browser_tab=財務会計システム`
- `window=受発注在庫管理システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=getsujitsu_teigaku_torihikisaki_ichiran - Compatibility Mode - Word`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`

**Automation interpretation:** Candidate for request intake/routing/status updates; retain authorization.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_009 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 9 inferred occurrences across 7 sessions.

**Recorded time:** 5.3 minutes.

**Application footprint:** 6 distinct applications, 191 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `Microsoft Edge` (9 occurrences)
- `browser:HR人事給与システム` (7 occurrences)
- `Windows Explorer` (4 occurrences)
- `browser:受発注在庫管理システム` (3 occurrences)
- `Notepad` (3 occurrences)
- `browser:財務会計システム` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 93
- `APP_SWITCH`: 42
- `SCROLL`: 35
- `COPY`: 22
- `SHORTCUT`: 8
- `NAVIGATE`: 7

**Representative evidence:**
- `window=File Explorer`
- `text=alt+f4`
- `browser_tab=HR人事給与システム`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `window=受発注在庫管理システム - Profile 1 - Microsoft​ Edge`
- `window=Home - File Explorer`
- `browser_tab=受発注在庫管理システム`
- `window=*精算確認メモ - Notepad`
- `window=HR人事給与システム and 1 more page - Profile 1 - Microsoft​ Edge`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `window=*IT申請メモ - Notepad`
- `window=shinkuitorihikisaki_touroku_tetsuzuki - Compatibility Mode - Word`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_011 — Budget analysis / financial planning support

**Confidence:** high

**Observed volume:** 7 inferred occurrences across 1 sessions.

**Recorded time:** 2.9 minutes.

**Application footprint:** 4 distinct applications, 108 observed application switches.

**Entity evidence:** 16 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- Budget analysis / financial planning support — matched 7 evidence occurrences across 7 workflow occurrences (100.0% coverage).
  - Cues: `budget_analysis` × 7
  - The same budget-analysis Excel artifact appears repeatedly with the financial-accounting system.

**Dominant application cues:**
- `Microsoft Edge` (7 occurrences)
- `Microsoft Excel` (7 occurrences)
- `browser:財務会計システム` (7 occurrences)
- `browser:HR人事給与システム` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 52
- `APP_SWITCH`: 22
- `SHORTCUT`: 21
- `SCROLL`: 20
- `TEXT_ENTRY`: 14
- `COPY`: 9
- `NAVIGATE`: 1

**Representative evidence:**
- `window=budget_analysis - Excel`
- `text=ctrl+end`
- `target_field=control_type=Pane class_name=EXCEL6`
- `text=ctrl+s`
- `text=alt+f4`
- `window=Opening - Excel`
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `browser_tab=財務会計システム`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `browser_tab=HR人事給与システム`
- `text==960`
- `target_field=name=I6 control_type=DataItem class_name=XLSpreadsheetCell automation_id=I6`

**Automation interpretation:** Candidate for spreadsheet preparation/calculation automation with analyst review.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_012 — Financial-accounting record review / administrative handling

**Confidence:** low

**Observed volume:** 5 inferred occurrences across 5 sessions.

**Recorded time:** 3.1 minutes.

**Application footprint:** 3 distinct applications, 129 observed application switches.

**Entity evidence:** 1 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `Microsoft Edge` (5 occurrences)
- `browser:財務会計システム` (4 occurrences)
- `OpenWith` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 72
- `SCROLL`: 26
- `COPY`: 14
- `APP_SWITCH`: 5
- `SHORTCUT`: 3
- `TEXT_ENTRY`: 2
- `NAVIGATE`: 1
- `OTHER`: 1

**Representative evidence:**
- `window=財務会計システム - Profile 1 - Microsoft​ Edge`
- `browser_tab=財務会計システム`
- `window=Restore pages`
- `text=ctrl+end`
- `text==31`
- `target_field=name=Just once control_type=Button class_name=Button automation_id=OpenWith_OnceButton`
- `text=04090`
- `target_field=name=Excel control_type=ListItem class_name=ListViewItem`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_017 — HR-system record review / administrative handling

**Confidence:** low

**Observed volume:** 3 inferred occurrences across 2 sessions.

**Recorded time:** 1.1 minutes.

**Application footprint:** 6 distinct applications, 14 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `browser:HR人事給与システム` (1 occurrences)
- `browser:受発注在庫管理システム` (1 occurrences)
- `browser:財務会計システム` (1 occurrences)
- `ms-teams` (1 occurrences)
- `procmine-desktop-agent` (1 occurrences)
- `Microsoft Edge` (1 occurrences)

**Dominant activity types:**
- `APP_SWITCH`: 22
- `CLICK`: 13
- `SCROLL`: 9
- `OTHER`: 8
- `NAVIGATE`: 7
- `COPY`: 3

**Representative evidence:**
- `window=Settings | Microsoft Teams`
- `window=Notepad`
- `window=Untitled and 2 more pages - Profile 1 - Microsoft​ Edge`
- `browser_tab=受発注在庫管理システム`
- `browser_tab=HR人事給与システム`
- `browser_tab=財務会計システム`
- `window=ProcMine Agent`
- `window=Untitled - Profile 1 - Microsoft​ Edge`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`

**Automation interpretation:** Not specific enough yet; inspect underlying occurrences before designing automation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_019 — HR case/comment entry or confirmation

**Confidence:** medium

**Observed volume:** 3 inferred occurrences across 2 sessions.

**Recorded time:** 1.1 minutes.

**Application footprint:** 4 distinct applications, 20 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- HR case/comment entry or confirmation — matched 1 evidence occurrences across 1 workflow occurrences (33.3% coverage).
  - Cues: `処理内容・確認コメントを入力してください` × 1
  - The UI explicitly requests processing-content/confirmation-comment entry in the HR system.

**Dominant application cues:**
- `Notepad` (2 occurrences)
- `Microsoft Edge` (2 occurrences)
- `WindowsTerminal` (1 occurrences)
- `browser:HR人事給与システム` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 13
- `APP_SWITCH`: 6
- `SCROLL`: 5
- `COPY`: 3
- `TEXT_ENTRY`: 1
- `OTHER`: 1

**Representative evidence:**
- `window=*在庫調整メモ - Notepad`
- `window=Windows PowerShell`
- `window=HR人事給与システム - Profile 1 - Microsoft​ Edge`
- `browser_tab=HR人事給与システム`
- `text=v`
- `target_field=name=処理内容・確認コメントを入力してください… control_type=Edit class_name=input automation_id=pi-note`

**Automation interpretation:** Potential support automation; inspect concrete steps before implementation.

_Note: this workflow name is inferred, not ground truth._

### WORKFLOW_020 — Order/inventory-system record review / administrative handling

**Confidence:** low

**Observed volume:** 2 inferred occurrences across 1 sessions.

**Recorded time:** 1.0 minutes.

**Application footprint:** 2 distinct applications, 1 observed application switches.

**Entity evidence:** 0 explicit entity values (absence is not proof that the underlying business system has no case ID).

**Why this name was assigned:**
- No distinctive repeated business-document/UI cue was strong enough for a narrower name.

**Dominant application cues:**
- `ms-teams` (2 occurrences)
- `browser:受発注在庫管理システム` (1 occurrences)

**Dominant activity types:**
- `CLICK`: 2
- `SCROLL`: 2
- `APP_SWITCH`: 2
- `NAVIGATE`: 1

**Representative evidence:**
- `window=Microsoft Teams`
- `browser_tab=受発注在庫管理システム`

**Automation interpretation:** Candidate for memo-to-system transcription/validation automation; retain final adjustment approval.

_Note: this workflow name is inferred, not ground truth._

## Automation candidate discussion

The following are candidates for further inspection, not guaranteed ROI estimates.
The prototype should target a workflow with clear repeated steps and observable
data transfer, while leaving business approvals or sensitive decisions to a human.

- **WORKFLOW_006 — Supplier / business-partner / contract administration**: Partial automation candidate: document preparation and cross-system data transfer; retain business decisions.
- **WORKFLOW_014 — Outsourced-work acceptance / expense administration**: Candidate for data collection, calculation and cross-system entry automation; retain approval.
- **WORKFLOW_010 — New-hire onboarding / employee joining verification**: Good candidate for checklist/data-transfer automation; retain human HR approval.
- **WORKFLOW_007 — HR-system record review / administrative handling**: Not specific enough yet; inspect underlying occurrences before designing automation.
- **WORKFLOW_003 — Expense calculation / settlement support**: Candidate for data collection, calculation and cross-system entry automation; retain approval.
- **WORKFLOW_015 — Expense settlement confirmation**: Candidate for data collection, calculation and cross-system entry automation; retain approval.
- **WORKFLOW_016 — Administrator access / permission request**: Candidate for request intake/routing/status updates; retain authorization.

## Important limitations

- `WORKFLOW_*_EXEC_*` IDs are generated occurrence IDs, not original source execution IDs.
- Process names are inferred from repeated evidence; Dataset B has no ground truth.
- Exact activity-type sequence counts should not be interpreted as business-variant counts.
- The recorded minutes are only the observed durations in the dataset; they are not a production ROI estimate.
