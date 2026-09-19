#!/usr/bin/env python3
"""Diagnostic for process-discovery signature quality on Dataset A.

This does NOT fit the final B pipeline. It compares two segment sets on the
same sessions:
  1) v6 predicted segments
  2) oracle GT segments
using the exact structural representation from process_discovery.py.

Purpose: determine whether poor A purity comes from noisy segmentation or from
an inadequate execution signature/clustering method.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import adjusted_rand_score

import process_discovery as pd


def gt_records_for_sessions(activities, gt_by_sid, sessions):
    records = []
    for sid in sorted(sessions):
        acts = activities.get(sid, [])
        for idx, seg in enumerate(gt_by_sid.get(sid, []), 1):
            seg2 = dict(seg)
            seg2["session_id"] = sid
            seg2["_start"] = seg["start"]
            seg2["_end"] = seg["end"]
            seg_acts = pd.segment_activities(acts, seg2)
            if not seg_acts:
                continue
            doc, meta = pd.signature_tokens(seg_acts)
            meta.update({
                "session_id": sid,
                "segment_index": idx,
                "start_ts": seg["start"],
                "end_ts": seg["end"],
                "start": seg2.get("start"),
                "end": seg2.get("end"),
                "process_code": seg.get("process_code"),
                "doc": doc,
            })
            records.append(meta)
    return records


def cluster_stats(records, thresholds):
    docs = [r["doc"] for r in records]
    X = pd.choose_feature_matrix(docs, records)
    rows = []
    for t in thresholds:
        labels = pd.cluster_matrix(X, t)
        rows.append((t, X, labels))
    return rows


def purity_from_codes(labels, truth):
    usable = [i for i, x in enumerate(truth) if x is not None]
    if not usable:
        return 0.0
    total = 0
    for lab in sorted(set(int(labels[i]) for i in usable)):
        vals = [truth[i] for i in usable if int(labels[i]) == lab]
        total += Counter(vals).most_common(1)[0][1]
    return total / len(usable)


def contamination(records, activities, gt_by_sid):
    contaminated = 0
    total = 0
    for r in records:
        sid = r["session_id"]
        seg = {"_start": r["start_ts"], "_end": r["end_ts"]}
        acts = pd.segment_activities(activities.get(sid, []), seg)
        owners = []
        for a in acts:
            best = None
            best_ov = -1.0
            for g in gt_by_sid.get(sid, []):
                ov = pd.interval_overlap(a["_start"], a["_end"], g["start"], g["end"])
                if ov > best_ov:
                    best_ov = ov
                    best = g.get("process_code") if best_ov > 0 else None
            if best is not None:
                owners.append(best)
        if owners:
            majority = Counter(owners).most_common(1)[0][0]
            total += len(owners)
            contaminated += sum(x != majority for x in owners)
    return contaminated / total if total else 0.0


def summarize(name, records, gt_codes=None):
    print(f"\n=== {name} ===")
    print(f"segments with activity evidence: {len(records):,}")
    if not records:
        return
    thresholds = [0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
    rows = cluster_stats(records, thresholds)
    truth = [r.get("process_code") for r in records] if gt_codes is None else gt_codes
    best_purity = (-1.0, None, None)
    best_ari = (-1.0, None, None)
    print("threshold | clusters | purity | ARI")
    print("----------+----------+--------+------")
    for t, X, labels in rows:
        usable = [i for i, x in enumerate(truth) if x is not None]
        if usable:
            p = purity_from_codes(labels, truth)
            a = adjusted_rand_score([truth[i] for i in usable], [int(labels[i]) for i in usable])
        else:
            p = 0.0
            a = 0.0
        k = len(set(labels.tolist()))
        print(f"{t:9.2f} | {k:8d} | {p:6.4f} | {a:4.4f}")
        if p > best_purity[0]:
            best_purity = (p, t, k)
        if a > best_ari[0]:
            best_ari = (a, t, k)
    print(f"best purity: {best_purity[0]:.4f} at threshold={best_purity[1]:.2f}, clusters={best_purity[2]}")
    print(f"best ARI:    {best_ari[0]:.4f} at threshold={best_ari[1]:.2f}, clusters={best_ari[2]}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activities", required=True)
    ap.add_argument("--predicted-segments", required=True)
    ap.add_argument("--gt", required=True)
    args = ap.parse_args()

    activities = pd.load_activities(Path(args.activities))
    predicted = pd.load_segments(Path(args.predicted_segments))
    gt_raw = json.loads(Path(args.gt).read_text(encoding="utf-8"))
    gt_by_sid = {}
    for s in gt_raw.get("sessions", []):
        sid = s.get("session_id")
        if not sid:
            continue
        rows = []
        for seg in s.get("segments", []):
            rows.append({
                "start": pd.parse_ts(seg["start"]),
                "end": pd.parse_ts(seg["end"]),
                "process_code": seg.get("process_code"),
                "execution_id": seg.get("execution_id"),
            })
        rows.sort(key=lambda x: (x["start"], x["end"], str(x.get("execution_id"))))
        gt_by_sid[sid] = rows

    sessions = sorted(predicted)
    pred_records = pd.build_dataset(activities, predicted)
    pred_codes = []
    for r in pred_records:
        sid = r["session_id"]
        best = None
        best_ov = -1.0
        for g in gt_by_sid.get(sid, []):
            ov = pd.interval_overlap(r["start_ts"], r["end_ts"], g["start"], g["end"])
            if ov > best_ov:
                best_ov = ov
                best = g.get("process_code") if best_ov > 0 else None
        pred_codes.append(best)

    gt_records = gt_records_for_sessions(activities, gt_by_sid, sessions)
    print("PROCESS DISCOVERY DIAGNOSTIC")
    print("=" * 78)
    print(f"sessions compared: {len(sessions)}")
    print(f"predicted segments: {sum(len(v) for v in predicted.values()):,}")
    print(f"GT segments in those sessions: {sum(sum(1 for x in gt_by_sid.get(s, [])) for s in sessions):,}")
    print(f"predicted segment activity contamination: {contamination(pred_records, activities, gt_by_sid):.4f}")

    summarize("PREDICTED V6 SEGMENTS", pred_records, pred_codes)
    summarize("ORACLE GT SEGMENTS", gt_records, [r.get("process_code") for r in gt_records])
    print("\nINTERPRETATION")
    print("If oracle GT clustering is also poor, the signature/clustering method is the bottleneck.")
    print("If oracle clustering is good but predicted clustering is poor, v6 segmentation/assignment is the bottleneck.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
