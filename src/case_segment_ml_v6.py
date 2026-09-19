#!/usr/bin/env python3
"""
Boundary-first supervised segmentation pipeline.

Core idea:
    activities -> consecutive transition features -> P(same GT segment)
               -> change-point cuts -> non-overlapping segments

This deliberately does NOT learn "same execution" over arbitrary activity pairs.
That target mixes two different concepts: an execution can be suspended/resumed,
while the required output is a contiguous active segment.

Dataset-A GT is used only to create adjacent transition labels during training and
to evaluate the held-out test set. Dataset-B must be applied without GT.

Design constraints:
- no A-specific application/URL/domain/entity vocabulary as model features
- split by exact-duplicate scenario groups, then by session
- deterministic ordering: start, end, activity_id
- no O(N^2) pair generation
- final segments never overlap
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DEFAULT_THRESHOLD_GRID = [0.35, 0.45, 0.55, 0.65, 0.75]
DEFAULT_MIN_DURATION_GRID = [0.0, 4.0, 8.0, 12.0]
DEFAULT_BOUNDARY_MODES = ["prev_end", "curr_start", "mid"]
ENTITY_TYPES = {
    "INVOICE_ID", "EMPLOYEE_ID", "CASE_ID", "DOCUMENT_ID", "CUSTOMER_ID",
    "ID_CANDIDATE", "EMAIL", "ORDER_ID", "PO_ID", "TRANSACTION_ID", "BANK_ID",
}


def parse_ts(v: Any) -> float:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Invalid timestamp: {v!r}")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"Timezone required: {v!r}")
    return dt.timestamp()


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def norm(v: Any) -> str:
    return " ".join(v.casefold().strip().split()) if isinstance(v, str) else ""


def safe_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def link_tokens(v: Any) -> set[str]:
    """Convert trigger/link references to stable hashable tokens.

    The frozen activity schema normally stores triggered_by as strings, but
    older activity exports may contain dictionaries. The ML feature only needs
    to know whether the two activities share a trigger reference, so normalize
    both forms without ever putting raw dictionaries into a set.
    """
    out: set[str] = set()
    for item in safe_list(v):
        if isinstance(item, str):
            if item:
                out.add(item)
            continue

        if isinstance(item, dict):
            found_id = False
            for key in ("event_id", "activity_id", "source_event_id", "id"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    # Include both the raw identifier and a typed token so
                    # string/dict representations of the same reference match.
                    out.add(value)
                    out.add(f"{key}:{value}")
                    found_id = True
            if not found_id:
                try:
                    out.add(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
                except (TypeError, ValueError):
                    out.add(repr(item))
            continue

        out.add(str(item))
    return out


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def jaccard_chars(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) < 2:
        return 0.0
    sa = {a[i:i+2] for i in range(len(a)-1)}
    sb = {b[i:i+2] for i in range(len(b)-1)}
    u = sa | sb
    return len(sa & sb) / len(u) if u else 0.0


def entity_keys(a: dict[str, Any]) -> set[str]:
    out = set()
    for e in safe_list(a.get("entities")):
        if not isinstance(e, dict):
            continue
        typ = norm(e.get("type"))
        val = norm(e.get("value"))
        if typ in ENTITY_TYPES and val:
            out.add(f"{typ}:{val}")
    return out


def entity_types(a: dict[str, Any]) -> set[str]:
    out = set()
    for e in safe_list(a.get("entities")):
        if isinstance(e, dict):
            typ = norm(e.get("type"))
            if typ in ENTITY_TYPES:
                out.add(typ)
    return out


def same_context_value(a: dict[str, Any], b: dict[str, Any], key: str) -> bool:
    av, bv = norm(a.get(key)), norm(b.get(key))
    return bool(av and bv and av == bv)


def feature_columns() -> tuple[list[str], list[str], list[str]]:
    numeric = [
        "log_gap_seconds", "overlap_ratio", "duration_ratio_log", "shared_entity_count",
        "shared_entity_type_count", "text_similarity", "screen_similarity", "entity_a_count",
        "entity_b_count",
    ]
    binary = [
        "same_app", "same_window", "same_browser_tab", "same_browser_domain", "same_activity_type",
        "triggered_by", "has_shared_entity", "a_before_b",
    ]
    categorical = ["activity_type_pair"]
    return numeric, binary, categorical


def _same_browser_domain(a: Any, b: Any) -> bool:
    import re
    def host(v: Any) -> str:
        s = norm(v)
        if not s:
            return ""
        s = re.sub(r"^[a-z]+://", "", s)
        s = s.split("/", 1)[0].split(":", 1)[0]
        return s
    ha, hb = host(a), host(b)
    return bool(ha and hb and ha == hb)


def build_features(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a0, a1 = a["_start"], a["_end"]
    b0, b1 = b["_start"], b["_end"]
    gap = max(0.0, b0 - a1) if b0 >= a1 else 0.0
    ov = interval_overlap(a0, a1, b0, b1)
    ad = max(0.001, a1 - a0)
    bd = max(0.001, b1 - b0)
    ea, eb = entity_keys(a), entity_keys(b)
    eta, etb = entity_types(a), entity_types(b)
    trig = bool(link_tokens(a.get("triggered_by")) & link_tokens(b.get("triggered_by")))
    return {
        "log_gap_seconds": math.log1p(gap),
        "overlap_ratio": ov / max(0.001, min(ad, bd)),
        "duration_ratio_log": math.log(max(ad, bd) / min(ad, bd)),
        "shared_entity_count": float(len(ea & eb)),
        "shared_entity_type_count": float(len(eta & etb)),
        "text_similarity": jaccard_chars(str(a.get("text") or ""), str(b.get("text") or "")),
        "screen_similarity": jaccard_chars(str(a.get("screen_text") or ""), str(b.get("screen_text") or "")),
        "entity_a_count": float(len(ea)),
        "entity_b_count": float(len(eb)),
        "same_app": int(same_context_value(a, b, "app")),
        "same_window": int(same_context_value(a, b, "window")),
        "same_browser_tab": int(same_context_value(a, b, "browser_tab")),
        "same_browser_domain": int(_same_browser_domain(a.get("browser_url"), b.get("browser_url"))),
        "same_activity_type": int(norm(a.get("type")) == norm(b.get("type"))),
        "triggered_by": int(trig),
        "has_shared_entity": int(bool(ea & eb)),
        "a_before_b": int(a0 <= b0),
        "activity_type_pair": f"{norm(a.get('type'))}|{norm(b.get('type'))}",
    }


def prepare_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    numeric, binary, categorical = feature_columns()
    return pd.DataFrame(rows, columns=numeric + binary + categorical)


def build_model() -> Pipeline:
    numeric, binary, categorical = feature_columns()
    pre = ColumnTransformer([
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
        ("bin", SimpleImputer(strategy="most_frequent"), binary),
        ("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), categorical),
    ])
    clf = LogisticRegression(max_iter=1000, class_weight="balanced", solver="liblinear", random_state=42)
    return Pipeline([("prep", pre), ("clf", clf)])


def load_activities(path: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            sid = row.get("session_id")
            aid = row.get("activity_id")
            if not isinstance(sid, str) or not sid or not isinstance(aid, str) or not aid:
                raise ValueError(f"{path}:{line_no}: missing session_id/activity_id")
            if aid in seen:
                raise ValueError(f"duplicate activity_id: {aid}")
            seen.add(aid)
            row["_start"], row["_end"] = parse_ts(row["start"]), parse_ts(row["end"])
            if row["_end"] < row["_start"]:
                raise ValueError(f"activity end < start: {aid}")
            out[sid].append(row)
    for rows in out.values():
        rows.sort(key=lambda x: (x["_start"], x["_end"], x["activity_id"]))
    if not out:
        raise ValueError("no activities")
    return dict(out)


def load_gt(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        gt = json.load(f)
    if gt.get("schema_version") != "ground_truth_reconstruction_v3":
        raise ValueError(f"expected GT v3, got {gt.get('schema_version')!r}")
    return gt


def scenario_groups(gt: dict[str, Any]) -> dict[str, str]:
    """Keep exact duplicate recordings in one split group."""
    groups = {}
    for s in gt["sessions"]:
        sid = s["session_id"]
        sig = {
            "session": s.get("session", {}),
            "segments": [(x.get("process_code"), x.get("start"), x.get("end"), x.get("execution_id")) for x in s.get("segments", [])],
        }
        digest = hashlib.sha256(json.dumps(sig, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        groups[sid] = digest
    return groups


def split_sessions(session_ids: list[str], groups: dict[str, str], test_fraction: float = 0.20) -> tuple[list[str], list[str]]:
    by_group = defaultdict(list)
    for sid in sorted(session_ids):
        by_group[groups[sid]].append(sid)
    keys = sorted(by_group)
    rng = random.Random(42)
    rng.shuffle(keys)
    target = max(1, int(round(len(session_ids) * test_fraction)))
    test_groups, n = [], 0
    for g in keys:
        if n >= target:
            break
        test_groups.append(g)
        n += len(by_group[g])
    test_set = {s for g in test_groups for s in by_group[g]}
    train = [s for s in sorted(session_ids) if s not in test_set]
    test = [s for s in sorted(session_ids) if s in test_set]
    return train, test


def assign_activity_to_gt_segment(rows: list[dict[str, Any]], gt_segments: list[dict[str, Any]]) -> dict[str, str | None]:
    """Assign each activity to the GT segment that contains/overlaps it.

    Critical detail: most activities are point events with start == end.
    Ordinary interval-overlap is zero for a point event, even when the event
    occurs *inside* a GT segment. The previous implementation therefore marked
    almost every activity as unresolved, collapsing the training target to
    essentially all zeros.

    For point activities we use timestamp containment. For positive-duration
    activities we use maximum temporal overlap, with the midpoint as a
    deterministic tie-break. At an exact boundary shared by two GT segments,
    prefer the segment whose start equals the activity timestamp (the new
    segment), then prefer the later segment start.
    """
    segments = [
        (g["segment_id"], parse_ts(g["start"]), parse_ts(g["end"]))
        for g in gt_segments
    ]
    segments.sort(key=lambda x: (x[1], x[2], x[0]))
    out: dict[str, str | None] = {}
    POINT_EPS = 1e-9

    for a in rows:
        a0, a1 = a["_start"], a["_end"]
        if a1 - a0 <= POINT_EPS:
            t = a0
            containing = [(gid, g0, g1) for gid, g0, g1 in segments if g0 <= t <= g1]
            if containing:
                # Exact segment start wins; otherwise latest-starting segment.
                containing.sort(key=lambda x: (x[1] == t, x[1]), reverse=True)
                out[a["activity_id"]] = containing[0][0]
            else:
                out[a["activity_id"]] = None
            continue

        best = None
        best_ov = 0.0
        best_dist = float("inf")
        for gid, g0, g1 in segments:
            ov = interval_overlap(a0, a1, g0, g1)
            if ov > best_ov:
                best = gid
                best_ov = ov
                best_dist = abs(((a0 + a1) / 2) - ((g0 + g1) / 2))
            elif ov > 0 and ov == best_ov:
                d = abs(((a0 + a1) / 2) - ((g0 + g1) / 2))
                if d < best_dist or (d == best_dist and g0 > (next((x[1] for x in segments if x[0] == best), -float("inf")))):
                    best = gid
                    best_dist = d
        out[a["activity_id"]] = best if best_ov > 0 else None
    return out


def make_transition_rows(by_session: dict[str, list[dict[str, Any]]], gt: dict[str, Any], sessions: list[str]) -> tuple[list[dict[str, Any]], list[int]]:
    gt_by_sid = {s["session_id"]: s for s in gt["sessions"]}
    feature_rows: list[dict[str, Any]] = []
    labels: list[int] = []
    for sid in sessions:
        rows = by_session.get(sid, [])
        segs = gt_by_sid[sid].get("segments", [])
        owners = assign_activity_to_gt_segment(rows, segs)
        for a, b in zip(rows, rows[1:]):
            fa = owners[a["activity_id"]]
            fb = owners[b["activity_id"]]
            # Same GT segment is the target for boundary continuity.
            y = int(fa is not None and fa == fb)
            feature_rows.append(build_features(a, b))
            labels.append(y)
    return feature_rows, labels


def boundary_counts(pred_ts: list[float], gt_ts: list[float], tolerance: float) -> tuple[int, int, int]:
    pred = sorted(pred_ts)
    gt = sorted(gt_ts)
    used = set()
    tp = 0
    for p in pred:
        best = None
        best_d = float("inf")
        for i, g in enumerate(gt):
            if i in used:
                continue
            d = abs(p - g)
            if d <= tolerance and d < best_d:
                best, best_d = i, d
        if best is not None:
            used.add(best)
            tp += 1
    return tp, len(pred) - tp, len(gt) - tp


def counts_to_metrics(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": p, "recall": r, "f1": 2*p*r/(p+r) if p+r else 0.0}

def boundary_time(prev: dict[str, Any], cur: dict[str, Any], mode: str) -> float:
    if mode == "prev_end":
        return prev["_end"]
    if mode == "curr_start":
        return cur["_start"]
    return (prev["_end"] + cur["_start"]) / 2.0


def make_runs_simple(rows: list[dict[str, Any]], same_prob: np.ndarray, threshold: float, min_duration: float, boundary_mode: str) -> list[dict[str, Any]]:
    """Stable implementation: build cuts, then iteratively merge shortest tiny runs."""
    n = len(rows)
    if n == 0:
        return []
    cuts = {i for i, p in enumerate(same_prob) if p < threshold}
    runs = []
    s = 0
    for i in range(n - 1):
        if i in cuts:
            runs.append([s, i])
            s = i + 1
    runs.append([s, n - 1])

    while len(runs) > 1 and min_duration > 0:
        tiny = []
        for j, (a, b) in enumerate(runs):
            if rows[b]["_end"] - rows[a]["_start"] < min_duration:
                tiny.append(j)
        if not tiny:
            break
        j = tiny[0]
        a, b = runs[j]
        if j == 0:
            runs[1][0] = a
        elif j == len(runs) - 1:
            runs[j-1][1] = b
        else:
            left_p = same_prob[a-1]
            right_p = same_prob[b]
            if left_p >= right_p:
                runs[j-1][1] = b
            else:
                runs[j+1][0] = a
        runs.pop(j)

    out = []
    for s, e in runs:
        st = rows[s]["_start"] if s == 0 else boundary_time(rows[s-1], rows[s], boundary_mode)
        en = rows[e]["_end"] if e == n-1 else boundary_time(rows[e], rows[e+1], boundary_mode)
        if en > st:
            out.append({"start_ts": st, "end_ts": en, "start_i": s, "end_i": e})
    return out


def session_boundary_metrics(predicted: dict[str, list[dict[str, Any]]], gt: dict[str, Any]) -> dict[str, dict[str, float]]:
    gt_by_sid = {s["session_id"]: s for s in gt["sessions"]}
    out = {}
    for tol in (0.5, 1.0, 2.0, 5.0):
        TP = FP = FN = 0
        for sid, rows in predicted.items():
            pred_ts = [x["start_ts"] for x in rows] + [x["end_ts"] for x in rows]
            gt_ts = []
            for g in gt_by_sid[sid].get("segments", []):
                gt_ts.extend([parse_ts(g["start"]), parse_ts(g["end"])])
            tp, fp, fn = boundary_counts(pred_ts, gt_ts, tol)
            TP += tp; FP += fp; FN += fn
        out[f"{tol:.1f}s"] = counts_to_metrics(TP, FP, FN)
    return out

def evaluate_prediction(predicted: dict[str, list[dict[str, Any]]], gt: dict[str, Any]) -> dict[str, Any]:
    return {
        "boundary": session_boundary_metrics(predicted, gt),
        "predicted_segments": sum(len(v) for v in predicted.values()),
    }


def oracle_prediction(by_session: dict[str, list[dict[str, Any]]], gt: dict[str, Any], threshold: float, min_duration: float, boundary_mode: str) -> dict[str, list[dict[str, Any]]]:
    """Use GT segment ownership to create ideal continuity probabilities (1 within same segment, 0 otherwise)."""
    gt_by_sid = {s["session_id"]: s for s in gt["sessions"]}
    out = {}
    for sid, rows in by_session.items():
        owners = assign_activity_to_gt_segment(rows, gt_by_sid[sid].get("segments", []))
        p = []
        for a, b in zip(rows, rows[1:]):
            oa, ob = owners[a["activity_id"]], owners[b["activity_id"]]
            p.append(1.0 if oa is not None and oa == ob else 0.0)
        out[sid] = make_runs_simple(rows, np.asarray(p, dtype=float), threshold, min_duration, boundary_mode)
    return out


def tune(pred_sessions: dict[str, list[dict[str, Any]]], gt: dict[str, Any]) -> tuple[float, float, str, dict[str, Any]]:
    best = None
    for threshold in DEFAULT_THRESHOLD_GRID:
        for min_duration in DEFAULT_MIN_DURATION_GRID:
            for mode in DEFAULT_BOUNDARY_MODES:
                pred = {}
                for sid, rows in pred_sessions.items():
                    p = rows  # placeholder: replaced by caller-specific cached probs
                # caller does direct loop; kept for API symmetry
    raise RuntimeError("unused")


def preflight() -> None:
    a = {"activity_id":"a","session_id":"s","start":"2026-01-01T00:00:00Z","end":"2026-01-01T00:00:01Z","type":"CLICK","app":"x","window":"w","browser_tab":"","browser_url":"","text":"abc","screen_text":"screen","entities":[]}
    b = dict(a); b.update(activity_id="b", start="2026-01-01T00:00:02Z", end="2026-01-01T00:00:03Z", type="APP_SWITCH")
    c = dict(a); c.update(activity_id="c", start="2026-01-01T00:00:08Z", end="2026-01-01T00:00:09Z")
    for x in (a,b,c):
        x["_start"], x["_end"] = parse_ts(x["start"]), parse_ts(x["end"])
    f = build_features(a,b)
    forbidden = {"app_value","window_value","browser_url_value","entity_value"}
    assert not forbidden & set(f)
    assert build_features(a,b)["same_app"] == build_features(b,a)["same_app"]

    # Older activity exports may encode triggered_by references as dictionaries.
    # This must remain a valid structural feature and must never crash training.
    a["triggered_by"] = [{"event_id": "evt-1"}]
    b["triggered_by"] = [{"event_id": "evt-1"}]
    dict_trigger_features = build_features(a, b)
    assert dict_trigger_features["triggered_by"] == 1
    a["triggered_by"] = [{"event_id": "evt-2"}]
    assert build_features(a, b)["triggered_by"] == 0
    probs = np.asarray([0.9, 0.1])
    segs = make_runs_simple([a,b,c], probs, 0.5, 0.0, "prev_end")
    assert len(segs) == 2
    assert segs[0]["end_ts"] <= segs[1]["start_ts"]

    # Regression: point activities must be owned when their timestamp is inside
    # a GT segment; this is the exact failure mode seen on Dataset A.
    gt_probe = [
        {"segment_id": "g1", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:00:10Z"},
        {"segment_id": "g2", "start": "2026-01-01T00:00:10.100Z", "end": "2026-01-01T00:00:20Z"},
    ]
    p1 = dict(a); p1["_start"] = p1["_end"] = parse_ts("2026-01-01T00:00:05Z")
    p2 = dict(a); p2["activity_id"] = "p2"; p2["_start"] = p2["_end"] = parse_ts("2026-01-01T00:00:06Z")
    p3 = dict(a); p3["activity_id"] = "p3"; p3["_start"] = p3["_end"] = parse_ts("2026-01-01T00:00:15Z")
    owned = assign_activity_to_gt_segment([p1, p2, p3], gt_probe)
    assert owned["a"] == "g1"
    assert owned["p2"] == "g1"
    assert owned["p3"] == "g2"

    print("Preflight boundary-ML self-test: PASS (10 cases)")


def train(args: argparse.Namespace) -> int:
    t0 = perf_counter()
    preflight()
    activities = load_activities(Path(args.activities))
    gt = load_gt(Path(args.gt))
    sessions = sorted(set(activities) & {s["session_id"] for s in gt["sessions"]})
    groups = scenario_groups(gt)
    train_all, test = split_sessions(sessions, groups, args.test_fraction)
    train_s, val = split_sessions(train_all, groups, args.val_fraction)
    print(f"[ML] sessions={len(sessions)} train={len(train_s)} val={len(val)} test={len(test)}", flush=True)

    X_rows, y = make_transition_rows(activities, gt, train_s)
    print(f"[ML] training transitions: {len(y):,} ({sum(y):,} same / {len(y)-sum(y):,} boundary-or-unresolved) [{perf_counter()-t0:.1f}s]", flush=True)
    if sum(y) == 0:
        raise RuntimeError("GT activity ownership produced zero positive adjacent transitions; check timestamp-to-segment assignment")
    model = build_model()
    X = prepare_df(X_rows)
    model.fit(X, np.asarray(y, dtype=int))
    print(f"[ML] initial model fit complete [{perf_counter()-t0:.1f}s]", flush=True)

    def predict_session(sid: str) -> np.ndarray:
        rows = activities[sid]
        feats = [build_features(a,b) for a,b in zip(rows, rows[1:])]
        if not feats:
            return np.zeros(0, dtype=float)
        return model.predict_proba(prepare_df(feats))[:,1]

    val_probs = {sid: predict_session(sid) for sid in val}
    best = None
    for threshold in DEFAULT_THRESHOLD_GRID:
        for min_duration in DEFAULT_MIN_DURATION_GRID:
            for mode in DEFAULT_BOUNDARY_MODES:
                pred = {sid: make_runs_simple(activities[sid], val_probs[sid], threshold, min_duration, mode) for sid in val}
                m = session_boundary_metrics(pred, {"sessions":[s for s in gt["sessions"] if s["session_id"] in val]})
                score = (m["5.0s"]["f1"], m["2.0s"]["f1"], -sum(len(x) for x in pred.values()))
                if best is None or score > best[0]:
                    best = (score, threshold, min_duration, mode, m)
    assert best is not None
    _, threshold, min_duration, mode, val_metrics = best
    print(f"[ML] validation selection: threshold={threshold:.2f}, min_duration={min_duration:.1f}s, boundary_mode={mode}", flush=True)
    print(f"[ML] validation boundary F1 @5s={val_metrics['5.0s']['f1']:.6f}", flush=True)

    # Retrain on train + validation after tuning. Test remains untouched.
    fit_sessions = train_all
    X_rows2, y2 = make_transition_rows(activities, gt, fit_sessions)
    if sum(y2) == 0:
        raise RuntimeError("Final GT activity ownership produced zero positive adjacent transitions")
    final_model = build_model()
    final_model.fit(prepare_df(X_rows2), np.asarray(y2, dtype=int))
    print(f"[ML] final model fit complete on {len(fit_sessions)} sessions [{perf_counter()-t0:.1f}s]", flush=True)

    test_probs: dict[str, np.ndarray] = {}
    pair_y, pair_p = [], []
    gt_by_sid = {s["session_id"] : s for s in gt["sessions"]}
    for sid in test:
        rows = activities[sid]
        owners = assign_activity_to_gt_segment(rows, gt_by_sid[sid].get("segments", []))
        feats = []
        ys = []
        for a,b in zip(rows,rows[1:]):
            oa, ob = owners[a["activity_id"]], owners[b["activity_id"]]
            ys.append(int(oa is not None and oa == ob))
            feats.append(build_features(a,b))
        p = final_model.predict_proba(prepare_df(feats))[:,1] if feats else np.zeros(0)
        test_probs[sid] = p
        pair_y.extend(ys); pair_p.extend(p.tolist())

    pred = {sid: make_runs_simple(activities[sid], test_probs[sid], threshold, min_duration, mode) for sid in test}
    test_gt = {"sessions":[gt_by_sid[sid] for sid in test]}
    metrics = evaluate_prediction(pred, test_gt)
    pair_pred = [int(x >= 0.5) for x in pair_p]
    metrics["transition_classifier"] = {
        "precision": precision_score(pair_y, pair_pred, zero_division=0),
        "recall": recall_score(pair_y, pair_pred, zero_division=0),
        "f1": f1_score(pair_y, pair_pred, zero_division=0),
        "roc_auc": roc_auc_score(pair_y, pair_p) if len(set(pair_y)) == 2 else 0.0,
        "pr_auc": average_precision_score(pair_y, pair_p) if len(set(pair_y)) == 2 else 0.0,
    }
    oracle = oracle_prediction({sid: activities[sid] for sid in test}, test_gt, threshold=0.5, min_duration=min_duration, boundary_mode=mode)
    metrics["oracle_activity_ownership_ceiling"] = evaluate_prediction(oracle, test_gt)
    metrics["split"] = {"train": train_s, "validation": val, "test": test}
    metrics["selected"] = {"threshold": threshold, "min_duration": min_duration, "boundary_mode": mode}
    metrics["created_utc"] = datetime.now(timezone.utc).isoformat()

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    with (out/"model.pkl").open("wb") as f: pickle.dump(final_model, f)
    (out/"config.json").write_text(json.dumps({"threshold":threshold,"min_duration":min_duration,"boundary_mode":mode,"feature_columns":feature_columns()}, indent=2), encoding="utf-8")
    (out/"metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    with (out/"holdout_segments_candidates.jsonl").open("w",encoding="utf-8") as f:
        for sid in test:
            for idx, seg in enumerate(pred[sid],1):
                f.write(json.dumps({"session_id":sid,"start":iso_utc(seg["start_ts"]),"end":iso_utc(seg["end_ts"]),"label":f"WORK_{idx:04d}","_execution_segment":idx}, ensure_ascii=False)+"\n")

    print("BOUNDARY-FIRST SUPERVISED SEGMENTATION")
    print("="*78)
    print(f"Sessions:                  {len(sessions)}")
    print(f"Train / Val / Test:        {len(train_s)} / {len(val)} / {len(test)}")
    print(f"Training transitions:      {len(y2):,}")
    print(f"Selected threshold:        {threshold:.2f}")
    print(f"Selected min duration:     {min_duration:.1f}s")
    print(f"Boundary placement:        {mode}")
    print("\nHELD-OUT TRANSITION CLASSIFIER")
    print("-"*78)
    for k,v in metrics["transition_classifier"].items(): print(f"{k:<26}: {v:.6f}")
    print("\nHELD-OUT BOUNDARY F1")
    print("-"*78)
    for k,v in metrics["boundary"].items(): print(f"{k:<26}: {v['f1']:.6f}")
    print("\nORACLE OWNERSHIP CEILING")
    print("-"*78)
    for k,v in metrics["oracle_activity_ownership_ceiling"]["boundary"].items(): print(f"{k:<26}: {v['f1']:.6f}")
    print("\nWrote:")
    print(out/"model.pkl"); print(out/"config.json"); print(out/"metrics.json"); print(out/"holdout_segments_candidates.jsonl")
    return 0


def apply(args: argparse.Namespace) -> int:
    preflight()
    with (Path(args.model_dir)/"model.pkl").open("rb") as f: model = pickle.load(f)
    cfg = json.loads((Path(args.model_dir)/"config.json").read_text(encoding="utf-8"))
    activities = load_activities(Path(args.activities))
    threshold = args.threshold if args.threshold is not None else float(cfg["threshold"])
    min_duration = float(cfg["min_duration"])
    mode = str(cfg["boundary_mode"])
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    all_segments = []
    for sid, rows in sorted(activities.items()):
        feats = [build_features(a,b) for a,b in zip(rows,rows[1:])]
        probs = model.predict_proba(prepare_df(feats))[:,1] if feats else np.zeros(0)
        segs = make_runs_simple(rows, probs, threshold, min_duration, mode)
        for idx, seg in enumerate(segs,1):
            all_segments.append({"session_id":sid,"start":iso_utc(seg["start_ts"]),"end":iso_utc(seg["end_ts"]),"label":f"WORK_{idx:04d}"})
    # hard non-overlap check
    by_sid = defaultdict(list)
    for s in all_segments: by_sid[s["session_id"]].append(s)
    for sid, segs in by_sid.items():
        segs.sort(key=lambda x: (parse_ts(x["start"]),parse_ts(x["end"])))
        for a,b in zip(segs,segs[1:]):
            if parse_ts(b["start"]) < parse_ts(a["end"]):
                raise AssertionError(f"overlap in {sid}")
    path = out/"segments.jsonl"
    with path.open("w",encoding="utf-8") as f:
        for s in all_segments: f.write(json.dumps(s,ensure_ascii=False)+"\n")
    print(f"Wrote {len(all_segments)} segments to {path}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--activities", required=True)
    t.add_argument("--gt", required=True)
    t.add_argument("--out-dir", required=True)
    t.add_argument("--test-fraction", type=float, default=0.20)
    t.add_argument("--val-fraction", type=float, default=0.20)
    a = sub.add_parser("apply")
    a.add_argument("--activities", required=True)
    a.add_argument("--model-dir", required=True)
    a.add_argument("--out-dir", required=True)
    a.add_argument("--threshold", type=float, default=None)
    args = p.parse_args(argv)
    try:
        return train(args) if args.cmd == "train" else apply(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
