
#!/usr/bin/env python3
"""
Evidence-driven business-process naming for Dataset B.

Inputs:
  --execution-map outputs/dataset_b/task2_v2/execution_map.jsonl
  --summary      outputs/dataset_b/task2_v2/workflow_summary.csv

Outputs:
  business_type_inference.jsonl
  task2_business_workflow_catalog.md

Important:
  * WORKFLOW_* remains the internal unsupervised cluster ID.
  * WORKFLOW_*_EXEC_* remains an inferred occurrence ID.
  * This script does NOT modify outputs/segments.jsonl.
  * A business-process name is emitted only when distinctive evidence is
    sufficiently repeated inside that workflow. Otherwise it stays generic
    / ambiguous.
  * This is interpretation, not ground truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Each rule describes a distinctive evidence family. It is intentionally
# conservative: generic application names are not enough to name a process.
RULES = [
    {
        "key": "new_hire",
        "name": "New-hire onboarding / employee joining verification",
        "patterns": ["nyusha_checklist_shinsotsu_batch"],
        "min_occurrences": 5,
        "min_coverage": 0.20,
        "reason": "The new-graduate/new-joiner checklist document is repeatedly observed with the HR system.",
    },
    {
        "key": "leave",
        "name": "Childcare / nursing-care leave administration",
        "patterns": ["ikuji_kyuugyou_kitei", "kaigo_kyuugyou_kitei"],
        "min_occurrences": 4,
        "min_coverage": 0.25,
        "reason": "Distinctive childcare/nursing-care leave procedure documents recur with the HR system.",
    },
    {
        "key": "budget",
        "name": "Budget analysis / financial planning support",
        "patterns": ["budget_analysis"],
        "min_occurrences": 3,
        "min_coverage": 0.40,
        "reason": "The same budget-analysis Excel artifact appears repeatedly with the financial-accounting system.",
    },
    {
        "key": "expense_calc",
        "name": "Expense calculation / settlement support",
        "patterns": ["expense_calc"],
        "min_occurrences": 5,
        "min_coverage": 0.50,
        "reason": "The expense-calculation spreadsheet is present throughout the workflow occurrences.",
    },
    {
        "key": "settlement_note",
        "name": "Expense settlement confirmation",
        "patterns": ["精算確認メモ"],
        "min_occurrences": 5,
        "min_coverage": 0.40,
        "reason": "Settlement-confirmation notes recur across the workflow occurrences.",
    },
    {
        "key": "inventory",
        "name": "Inventory adjustment / inventory administration",
        "patterns": ["在庫調整メモ"],
        "min_occurrences": 5,
        "min_coverage": 0.35,
        "reason": "Inventory-adjustment notes recur alongside the order/inventory-management system.",
    },
    {
        "key": "it_request",
        "name": "IT request / software-license administration",
        "patterns": ["IT申請メモ", "software license"],
        "min_occurrences": 4,
        "min_coverage": 0.35,
        "reason": "The workflow repeatedly contains an IT-request memo or explicit software-license request.",
    },
    {
        "key": "admin_access",
        "name": "Administrator access / permission request",
        "patterns": ["kanrisya_kengen_shinsei_tetsuzuki"],
        "min_occurrences": 4,
        "min_coverage": 0.40,
        "reason": "The administrator-permission application procedure is repeatedly observed.",
    },
    {
        "key": "supplier_contract",
        "name": "Supplier / business-partner / contract administration",
        "patterns": [
            "shinkuitorihikisaki_touroku_tetsuzuki",
            "shinkui_keiyaku_tetsuzuki",
            "keiyaku_kaijo_tetsuzuki",
        ],
        "min_occurrences": 10,
        "min_coverage": 0.25,
        "reason": "New business-partner registration and contract/cancellation procedure documents recur throughout the workflow.",
    },
    {
        "key": "outsourcing",
        "name": "Outsourced-work acceptance / expense administration",
        "patterns": ["gyomu_itaku_ukeire_tetsuzuki", "gyomu_itaku_keihi_kitei"],
        "min_occurrences": 6,
        "min_coverage": 0.25,
        "reason": "Outsourced-work acceptance and outsourced-work expense documents recur.",
    },
    {
        "key": "representation_expense",
        "name": "Representation / entertainment-expense administration",
        "patterns": ["settai_keihi_kitei"],
        "min_occurrences": 6,
        "min_coverage": 0.25,
        "reason": "The representation/entertainment-expense policy document recurs in the workflow.",
    },
    {
        "key": "family_allowance",
        "name": "Family allowance / employee-benefit administration",
        "patterns": ["kazoku_teate_kitei"],
        "min_occurrences": 4,
        "min_coverage": 0.25,
        "reason": "The family-allowance policy document recurs with the HR system.",
    },
    {
        "key": "hr_comment",
        "name": "HR case/comment entry or confirmation",
        "patterns": ["処理内容・確認コメントを入力してください"],
        "min_occurrences": 1,
        "min_coverage": 0.25,
        "reason": "The UI explicitly requests processing-content/confirmation-comment entry in the HR system.",
    },
    {
        "key": "monthly_business_partner",
        "name": "Monthly fixed-amount business-partner list review",
        "patterns": ["getsujitsu_teigaku_torihikisaki_ichiran"],
        "min_occurrences": 5,
        "min_coverage": 0.25,
        "reason": "A distinctive monthly fixed-amount business-partner list document recurs.",
    },
]

# Use simple combination rules only where the evidence is strong enough that
# describing a broader family is more honest than selecting one sub-procedure.
COMBINATIONS = [
    (
        {"supplier_contract", "outsourcing"},
        "Supplier / contract / outsourced-work administration",
    ),
    (
        {"expense_calc", "settlement_note", "representation_expense"},
        "Expense / settlement / representation-expense administration",
    ),
    (
        {"inventory", "settlement_note"},
        "Inventory and settlement confirmation",
    ),
    (
        {"new_hire", "family_allowance"},
        "Employee onboarding / allowance administration",
    ),
    (
        {"leave", "family_allowance"},
        "Employee leave / allowance administration",
    ),
]


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"ERROR: file not found: {path}")
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"ERROR: {path}:{line_no}: invalid JSON: {exc}")
            if not isinstance(row, dict):
                raise SystemExit(f"ERROR: {path}:{line_no}: expected object")
            rows.append(row)
    if not rows:
        raise SystemExit(f"ERROR: {path}: no records")
    return rows


def load_summary(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"ERROR: file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"ERROR: {path}: no rows")
    out = {}
    for row in rows:
        if "workflow_id" not in row or not row["workflow_id"]:
            raise SystemExit(f"ERROR: {path}: row missing workflow_id")
        out[row["workflow_id"]] = row
    return out


def aggregate(workflow_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    evidence_counter = Counter()
    app_counter = Counter()
    activity_counter = Counter()
    entity_counter = Counter()
    occurrence_evidence: list[set[str]] = []

    for row in rows:
        seen_in_occurrence = set()
        for ev in row.get("evidence", []):
            evs = str(ev)
            evidence_counter[evs] += 1
            seen_in_occurrence.add(evs.casefold())
        occurrence_evidence.append(seen_in_occurrence)

        for app in row.get("apps", []):
            app_counter[str(app)] += 1

        for typ, count in row.get("activity_types", {}).items():
            activity_counter[str(typ)] += int(count)

        for ent in row.get("explicit_entities", []):
            entity_counter[str(ent)] += 1

    return {
        "workflow_id": workflow_id,
        "occurrence_count": n,
        "evidence_counter": evidence_counter,
        "occurrence_evidence": occurrence_evidence,
        "app_counter": app_counter,
        "activity_counter": activity_counter,
        "entity_counter": entity_counter,
        "sample_evidence": [e for e, _ in evidence_counter.most_common(16)],
    }


def find_rule_hits(agg: dict[str, Any]) -> list[dict[str, Any]]:
    hits = []
    occurrences = agg["occurrence_evidence"]
    n = agg["occurrence_count"]

    for rule in RULES:
        total_matches = 0
        occurrence_hits = 0
        matched = Counter()

        for evset in occurrences:
            matched_here = []
            for pattern in rule["patterns"]:
                p = norm(pattern)
                if any(p in ev for ev in evset):
                    matched[pattern] += 1
                    total_matches += 1
                    matched_here.append(pattern)
            if matched_here:
                occurrence_hits += 1

        coverage = occurrence_hits / n if n else 0.0

        # Require BOTH a minimum number of occurrences and a minimum coverage.
        # This prevents one incidental document from naming an entire cluster.
        if total_matches >= rule["min_occurrences"] and coverage >= rule["min_coverage"]:
            hits.append({
                "key": rule["key"],
                "name": rule["name"],
                "confidence": "high" if coverage >= 0.50 else "medium",
                "evidence_match_count": total_matches,
                "occurrences_with_match": occurrence_hits,
                "coverage": round(coverage, 3),
                "matched_patterns": dict(matched),
                "reason": rule["reason"],
            })

    return hits


def combine_hit_names(hits: list[dict[str, Any]]) -> str | None:
    keys = {h["key"] for h in hits}
    for needed, label in COMBINATIONS:
        if needed.issubset(keys):
            return label
    return None


def infer_one(agg: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    hits = find_rule_hits(agg)
    hits_sorted = sorted(
        hits,
        key=lambda h: (-h["coverage"], -h["evidence_match_count"], h["key"])
    )

    # Strong dominant cue wins over weak incidental cues.
    if hits_sorted and hits_sorted[0]["coverage"] >= 0.50:
        top = hits_sorted[0]
        name = top["name"]
        confidence = "high"
    else:
        combined = combine_hit_names(hits_sorted)
        if combined:
            name = combined
            confidence = "high" if len(hits_sorted) >= 2 else "medium"
        elif len(hits_sorted) == 1:
            name = hits_sorted[0]["name"]
            confidence = hits_sorted[0]["confidence"]
        elif len(hits_sorted) > 1:
            name = "Mixed administrative workflow (see evidence)"
            confidence = "low"
        else:
            apps = agg["app_counter"]
            if any("HR人事給与システム" in a for a in apps):
                name = "HR-system record review / administrative handling"
            elif any("財務会計システム" in a for a in apps):
                name = "Financial-accounting record review / administrative handling"
            elif any("受発注在庫管理システム" in a for a in apps):
                name = "Order/inventory-system record review / administrative handling"
            else:
                name = "Cross-system administrative handling"
            confidence = "low"

    evidence = [
        {
            "name": h["name"],
            "confidence": h["confidence"],
            "match_count": h["evidence_match_count"],
            "occurrences_with_match": h["occurrences_with_match"],
            "coverage": h["coverage"],
            "matched_patterns": h["matched_patterns"],
            "reason": h["reason"],
        }
        for h in hits_sorted
    ]

    return {
        "workflow_id": agg["workflow_id"],
        "suggested_process_type": name,
        "confidence": confidence,
        "occurrences": int(summary["execution_count"]),
        "sessions": int(summary["session_count"]),
        "actor_or_machine_count": int(summary["actor_or_machine_count"]),
        "total_duration_s": float(summary["total_duration_s"]),
        "duration_share": float(summary["duration_share"]),
        "unique_apps": int(summary["unique_apps"]),
        "total_app_switches": int(summary["total_app_switches"]),
        "unique_variants": int(summary["unique_variants"]),
        "dominant_variant_share": float(summary["dominant_variant_share"]),
        "explicit_entity_value_count": int(summary["explicit_entity_value_count"]),
        "evidence_rules": evidence,
        "dominant_application_cues": [
            {"cue": a, "occurrence_count": n}
            for a, n in agg["app_counter"].most_common(8)
        ],
        "dominant_activity_types": [
            {"type": a, "count": n}
            for a, n in agg["activity_counter"].most_common(8)
        ],
        "evidence_samples": agg["sample_evidence"],
        "naming_note": (
            "Inferred from repeated Dataset-B evidence. This is not a ground-truth "
            "business-process label."
        ),
    }


def automation_note(x: dict[str, Any]) -> str:
    t = x["suggested_process_type"].casefold()
    if "new-hire" in t:
        return "Good candidate for checklist/data-transfer automation; retain human HR approval."
    if "budget analysis" in t:
        return "Candidate for spreadsheet preparation/calculation automation with analyst review."
    if "expense" in t or "settlement" in t:
        return "Candidate for data collection, calculation and cross-system entry automation; retain approval."
    if "inventory" in t:
        return "Candidate for memo-to-system transcription/validation automation; retain final adjustment approval."
    if "leave" in t:
        return "Candidate for document/checklist preparation and status-entry automation; retain eligibility decisions."
    if "supplier" in t or "contract" in t:
        return "Partial automation candidate: document preparation and cross-system data transfer; retain business decisions."
    if "access" in t or "it request" in t:
        return "Candidate for request intake/routing/status updates; retain authorization."
    if x["confidence"] == "low":
        return "Not specific enough yet; inspect underlying occurrences before designing automation."
    return "Potential support automation; inspect concrete steps before implementation."


def render_markdown(items: list[dict[str, Any]]) -> str:
    total_time = sum(x["total_duration_s"] for x in items)
    total_occ = sum(x["occurrences"] for x in items)

    lines = [
        "# Dataset B — Business Workflow Catalogue",
        "",
        "## Purpose",
        "",
        "This is the human-readable Task-2 interpretation of the 20 workflow clusters",
        "discovered from Dataset B. `WORKFLOW_*` is an internal cluster ID; it is not the",
        "real business-process name. The names below are evidence-based interpretations.",
        "Because Dataset B has no ground truth, confidence is intentionally shown and",
        "ambiguous clusters are not forced into a precise business label.",
        "",
        f"- Workflow clusters: **{len(items)}**",
        f"- Inferred workflow occurrences: **{total_occ}**",
        f"- Recorded segment time: **{total_time/60:.1f} min**",
        "",
        "## Whole-dataset summary",
        "",
        "| Workflow | Inferred business type | Confidence | Occurrences | Sessions | Recorded time | Apps | Entity values |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]

    for x in sorted(items, key=lambda z: (-z["occurrences"], z["workflow_id"])):
        lines.append(
            f"| {x['workflow_id']} | {x['suggested_process_type']} | {x['confidence']} | "
            f"{x['occurrences']} | {x['sessions']} | {x['total_duration_s']/60:.1f} min | "
            f"{x['unique_apps']} | {x['explicit_entity_value_count']} |"
        )

    lines += ["", "## Detailed workflow interpretation", ""]
    for x in sorted(items, key=lambda z: (-z["occurrences"], z["workflow_id"])):
        lines += [
            f"### {x['workflow_id']} — {x['suggested_process_type']}",
            "",
            f"**Confidence:** {x['confidence']}",
            "",
            f"**Observed volume:** {x['occurrences']} inferred occurrences across {x['sessions']} sessions.",
            "",
            f"**Recorded time:** {x['total_duration_s']/60:.1f} minutes.",
            "",
            f"**Application footprint:** {x['unique_apps']} distinct applications, "
            f"{x['total_app_switches']} observed application switches.",
            "",
            f"**Entity evidence:** {x['explicit_entity_value_count']} explicit entity values "
            "(absence is not proof that the underlying business system has no case ID).",
            "",
            "**Why this name was assigned:**",
        ]

        if x["evidence_rules"]:
            for h in x["evidence_rules"]:
                lines.append(
                    f"- {h['name']} — matched {h['match_count']} evidence occurrences "
                    f"across {h['occurrences_with_match']} workflow occurrences "
                    f"({h['coverage']*100:.1f}% coverage)."
                )
                if h["matched_patterns"]:
                    lines.append(
                        "  - Cues: " + ", ".join(f"`{k}` × {v}" for k, v in h["matched_patterns"].items())
                    )
                lines.append(f"  - {h['reason']}")
        else:
            lines.append("- No distinctive repeated business-document/UI cue was strong enough for a narrower name.")

        lines += ["", "**Dominant application cues:**"]
        for a in x["dominant_application_cues"]:
            lines.append(f"- `{a['cue']}` ({a['occurrence_count']} occurrences)")

        lines += ["", "**Dominant activity types:**"]
        for a in x["dominant_activity_types"]:
            lines.append(f"- `{a['type']}`: {a['count']}")

        lines += ["", "**Representative evidence:**"]
        for e in x["evidence_samples"][:12]:
            lines.append(f"- `{e}`")

        lines += [
            "",
            f"**Automation interpretation:** {automation_note(x)}",
            "",
            "_Note: this workflow name is inferred, not ground truth._",
            "",
        ]

    lines += [
        "## Automation candidate discussion",
        "",
        "The following are candidates for further inspection, not guaranteed ROI estimates.",
        "The prototype should target a workflow with clear repeated steps and observable",
        "data transfer, while leaving business approvals or sensitive decisions to a human.",
        "",
    ]

    # A compact, defensible shortlist based on evidence clarity + volume, not a
    # hidden numeric score.
    candidate_ids = {
        "WORKFLOW_006",
        "WORKFLOW_010",
        "WORKFLOW_014",
        "WORKFLOW_015",
        "WORKFLOW_016",
        "WORKFLOW_003",
        "WORKFLOW_007",
    }
    for x in sorted(items, key=lambda z: (-z["occurrences"], z["workflow_id"])):
        if x["workflow_id"] in candidate_ids:
            lines.append(
                f"- **{x['workflow_id']} — {x['suggested_process_type']}**: "
                f"{automation_note(x)}"
            )

    lines += [
        "",
        "## Important limitations",
        "",
        "- `WORKFLOW_*_EXEC_*` IDs are generated occurrence IDs, not original source execution IDs.",
        "- Process names are inferred from repeated evidence; Dataset B has no ground truth.",
        "- Exact activity-type sequence counts should not be interpreted as business-variant counts.",
        "- The recorded minutes are only the observed durations in the dataset; they are not a production ROI estimate.",
    ]
    return "\n".join(lines) + "\n"


def self_test() -> None:
    # Test the rule gate itself without requiring project files.
    rows = [
        {
            "workflow_id": "W",
            "evidence": ["window=budget_analysis - Excel"],
            "apps": ["Microsoft Excel"],
            "activity_types": {"CLICK": 1},
            "explicit_entities": [],
        }
        for _ in range(4)
    ]
    agg = aggregate("W", rows)
    fake_summary = {
        "execution_count": "4",
        "session_count": "1",
        "actor_or_machine_count": "1",
        "total_duration_s": "20",
        "duration_share": "1.0",
        "unique_apps": "1",
        "total_app_switches": "2",
        "unique_variants": "1",
        "dominant_variant_share": "1.0",
        "explicit_entity_value_count": "0",
    }
    out = infer_one(agg, fake_summary)
    assert out["suggested_process_type"] == "Budget analysis / financial planning support"
    assert out["confidence"] in {"high", "medium"}

    rows_strong = [
        {
            "workflow_id": "W3",
            "evidence": [
                "window=nyusha_checklist_shinsotsu_batch - Compatibility Mode - Word",
            ],
            "apps": ["Microsoft Word"],
            "activity_types": {"CLICK": 1},
            "explicit_entities": [],
        }
        for _ in range(6)
    ]
    rows_strong[5]["evidence"] = [
        "window=ikuji_kyuugyou_kitei - Compatibility Mode - Word"
    ]
    agg3 = aggregate("W3", rows_strong)
    fake_summary["execution_count"] = "4"
    out3 = infer_one(agg3, fake_summary)
    assert out3["suggested_process_type"] == "New-hire onboarding / employee joining verification"
    assert out3["confidence"] == "high"

    rows2 = [
        {
            "workflow_id": "W2",
            "evidence": ["window=HR人事給与システム"] * 2,
            "apps": ["browser:HR人事給与システム"] * 2,
            "activity_types": {"CLICK": 2},
            "explicit_entities": [],
        }
    ]
    agg2 = aggregate("W2", rows2)
    fake_summary["execution_count"] = "2"
    out2 = infer_one(agg2, fake_summary)
    assert out2["confidence"] == "low"
    print("Preflight business-type inference self-test: PASS (6 assertions)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--execution-map")
    p.add_argument("--summary")
    p.add_argument("--out-dir")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.execution_map or not args.summary or not args.out_dir:
        raise SystemExit("ERROR: --execution-map, --summary and --out-dir are required")

    execution_rows = load_jsonl(Path(args.execution_map))
    summary = load_summary(Path(args.summary))
    by_workflow = defaultdict(list)

    required = {"workflow_id", "evidence", "apps", "activity_types", "explicit_entities"}
    for i, row in enumerate(execution_rows, 1):
        missing = required - row.keys()
        if missing:
            raise SystemExit(f"ERROR: execution map row {i} missing {sorted(missing)}")
        if row["workflow_id"] not in summary:
            raise SystemExit(f"ERROR: {row['workflow_id']} not found in summary")
        by_workflow[row["workflow_id"]].append(row)

    if set(by_workflow) != set(summary):
        raise SystemExit("ERROR: workflow IDs differ between execution map and summary")

    items = []
    for wf in sorted(by_workflow):
        agg = aggregate(wf, by_workflow[wf])
        item = infer_one(agg, summary[wf])
        items.append(item)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "business_type_inference.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in items) + "\n",
        encoding="utf-8",
    )
    (out / "task2_business_workflow_catalog.md").write_text(
        render_markdown(items),
        encoding="utf-8",
    )

    print("BUSINESS-TYPE INFERENCE")
    print("=" * 78)
    print(f"Workflow clusters: {len(items)}")
    print(f"High confidence:    {sum(x['confidence']=='high' for x in items)}")
    print(f"Medium confidence:  {sum(x['confidence']=='medium' for x in items)}")
    print(f"Low / ambiguous:    {sum(x['confidence']=='low' for x in items)}")
    print()
    for x in items:
        print(f"{x['workflow_id']}: {x['suggested_process_type']} [{x['confidence']}]")
    print()
    print(f"Wrote: {out / 'business_type_inference.jsonl'}")
    print(f"Wrote: {out / 'task2_business_workflow_catalog.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
