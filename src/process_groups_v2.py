#!/usr/bin/env python3
"""
Constrained rule-based reconstruction of logical process executions.

v2 changes the T0 grouping logic using the Dataset-A error analysis:
- strong relationships can resume an earlier execution, but candidate choice is
  explicit and ambiguity is handled;
- context-only continuation is much stricter and local: immediate predecessor
  only, same app + (same window or same browser tab), score >= 4;
- context continuation cannot silently switch to a different explicit entity;
- the bridge time for strong evidence is measured to the actual related member;
- empty relationship files are accepted;
- deterministic preflight tests run before Dataset A.
"""
from __future__ import annotations
import argparse, json, sys, unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

STRONG_BRIDGE_MAX_SECONDS = 300.0
CONTEXT_CONTINUATION_MAX_SECONDS = 12.0
CONTEXT_SCORE_MIN = 4
STRONG_CANDIDATE_MARGIN = 2.0

COHERENT_ENTITY_TYPES = {
    "INVOICE_ID","EMPLOYEE_ID","CASE_ID","DOCUMENT_ID","CUSTOMER_ID",
    "ID_CANDIDATE","EMAIL","FILENAME","URL",
}
SYSTEM_TYPES = {"OTHER"}
SYSTEM_LAYERS = {"SYSTEM"}

def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid timestamp: {value!r}")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must contain timezone information: {value!r}")
    return dt

def norm(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).strip().casefold()

def load_jsonl(path: Path, allow_empty: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open("r", encoding="utf-8") as h:
        for line_no, raw in enumerate(h, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(obj)
    if not rows and not allow_empty:
        raise ValueError(f"{path} contains no records.")
    return rows

def validate_activities(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    required = {
        "activity_id","session_id","start","end","type","app","window",
        "browser_tab","browser_url","entities","source_layers",
    }
    seen = set()
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n, a in enumerate(records, 1):
        missing = required - set(a)
        if missing:
            raise ValueError(f"Activity record {n} missing fields: {sorted(missing)}")
        aid, sid = a["activity_id"], a["session_id"]
        if not isinstance(aid, str) or not aid:
            raise ValueError(f"Activity record {n}: invalid activity_id")
        if aid in seen:
            raise ValueError(f"Duplicate activity_id: {aid}")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"Activity {aid}: invalid session_id")
        start, end = parse_timestamp(a["start"]), parse_timestamp(a["end"])
        if end < start:
            raise ValueError(f"Activity {aid}: end before start")
        if not isinstance(a["entities"], list) or not isinstance(a["source_layers"], list):
            raise ValueError(f"Activity {aid}: entities/source_layers must be lists")
        a["_start_dt"], a["_end_dt"] = start, end
        a["_start_ts"], a["_end_ts"] = start.timestamp(), end.timestamp()
        seen.add(aid)
        by_session[sid].append(a)
    for items in by_session.values():
        items.sort(key=lambda a: (a["_start_dt"], a["_end_dt"], a["activity_id"]))
    return dict(by_session)

def build_relationship_index(relationships: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    idx: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    seen = set()
    for n, r in enumerate(relationships, 1):
        a, b, features = r.get("activity_a"), r.get("activity_b"), r.get("features")
        if not isinstance(a, str) or not isinstance(b, str):
            raise ValueError(f"Relationship {n}: activity_a/activity_b must be strings")
        if a == b:
            raise ValueError(f"Relationship {n}: self-link {a}")
        if not isinstance(features, dict):
            raise ValueError(f"Relationship {n}: missing features object")
        pair = tuple(sorted((a, b)))
        if pair in seen:
            raise ValueError(f"Duplicate relationship pair: {pair[0]} <-> {pair[1]}")
        seen.add(pair)
        idx[a][b] = features
        idx[b][a] = features
    return dict(idx)

def explicit_strong(features: dict[str, Any]) -> bool:
    return bool(features.get("same_entity") or features.get("triggered_by"))

def entity_keys(activity: dict[str, Any]) -> set[tuple[str, str]]:
    out = set()
    for e in activity.get("entities", []):
        if not isinstance(e, dict):
            continue
        typ, val = e.get("type"), e.get("value")
        if isinstance(typ, str) and isinstance(val, str):
            typ = typ.strip().upper()
            val = norm(val)
            if typ in COHERENT_ENTITY_TYPES and val:
                out.add((typ, val))
    return out

def context_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    aa, ab = norm(a.get("app")), norm(b.get("app"))
    if not aa or aa != ab:
        return False
    sw = bool(norm(a.get("window")) and norm(a.get("window")) == norm(b.get("window")))
    st = bool(norm(a.get("browser_tab")) and norm(a.get("browser_tab")) == norm(b.get("browser_tab")))
    return sw or st

def is_system_unassigned(a: dict[str, Any]) -> bool:
    layers = {str(x).upper() for x in a.get("source_layers", []) if isinstance(x, str)}
    return str(a.get("type", "")).upper() in SYSTEM_TYPES and layers and layers.issubset(SYSTEM_LAYERS)

class Execution:
    def __init__(self, session_id: str, number: int, first: dict[str, Any]):
        self.session_id = session_id
        self.number = number
        self.execution_id = f"{session_id}:exec-{number:04d}"
        self.activity_ids: list[str] = []
        self.member_indices: list[int] = []
        self.entity_keys: set[tuple[str, str]] = set()
        self.first_dt = first["_start_dt"]
        self.last_dt = first["_end_dt"]
        self.segments: list[list[int]] = []
        self._current_segment: list[int] = []
    def add(self, index: int, activity: dict[str, Any]) -> None:
        self.activity_ids.append(activity["activity_id"])
        self.member_indices.append(index)
        self.entity_keys.update(entity_keys(activity))
        self.last_dt = activity["_end_dt"]
        self._current_segment.append(index)
    def close_contiguous_segment(self) -> None:
        if self._current_segment:
            self.segments.append(self._current_segment)
            self._current_segment = []
    def finish(self) -> None:
        self.close_contiguous_segment()
    @property
    def member_count(self) -> int:
        return len(self.member_indices)

def strong_rank(features: dict[str, Any], delta: float) -> float:
    score = float(features.get("score", 0))
    if features.get("triggered_by"):
        score += 3.0
    if features.get("same_entity"):
        score += 1.0
    return score + max(0.0, 1.0 - min(delta, STRONG_BRIDGE_MAX_SECONDS) / STRONG_BRIDGE_MAX_SECONDS)

def strong_candidates(
    current: dict[str, Any],
    execution_by_activity_id: dict[str, Execution],
    activities_by_id: dict[str, dict[str, Any]],
    rel_idx: dict[str, dict[str, dict[str, Any]]],
) -> list[tuple[Execution, dict[str, Any]]]:
    result: dict[str, tuple[Execution, dict[str, Any]]] = {}
    for related_id, features in rel_idx.get(current["activity_id"], {}).items():
        if not explicit_strong(features):
            continue
        ex = execution_by_activity_id.get(related_id)
        related = activities_by_id.get(related_id)
        if ex is None or related is None:
            continue
        delta = abs(current["_start_ts"] - related["_start_ts"])
        if delta > STRONG_BRIDGE_MAX_SECONDS:
            continue
        # Same-entity evidence itself cannot conflict with the group's known entities.
        # Trigger links are allowed to connect different entities.
        if features.get("same_entity"):
            ck, ek = entity_keys(current), ex.entity_keys
            if ck and ek and not ck.intersection(ek):
                continue
        cand = {
            "mode": "STRONG",
            "features": features,
            "member_activity_id": related_id,
            "delta_seconds": delta,
            "rank": strong_rank(features, delta),
        }
        prev = result.get(ex.execution_id)
        if prev is None or cand["rank"] > prev[1]["rank"]:
            result[ex.execution_id] = (ex, cand)
    return list(result.values())

def choose_strong(cands: list[tuple[Execution, dict[str, Any]]]) -> tuple[Execution|None, dict[str, Any]|None, str]:
    if not cands:
        return None, None, "NONE"
    cands = sorted(cands, key=lambda x: (x[1]["rank"], -x[1]["delta_seconds"], x[0].execution_id), reverse=True)
    best, ev = cands[0]
    if len(cands) == 1:
        return best, ev, "UNIQUE"
    second, ev2 = cands[1]
    if ev["rank"] - ev2["rank"] >= STRONG_CANDIDATE_MARGIN:
        return best, ev, "MARGIN_OK"
    e1 = {tuple((e.get("type"), e.get("value"))) for e in ev["features"].get("shared_entities", []) if isinstance(e, dict)}
    e2 = {tuple((e.get("type"), e.get("value"))) for e in ev2["features"].get("shared_entities", []) if isinstance(e, dict)}
    if e1 and e1 == e2:
        return best, ev, "SAME_ENTITY_TIE"
    return None, None, "AMBIGUOUS"

def context_candidate(
    current: dict[str, Any],
    prev_activity: dict[str, Any] | None,
    prev_execution: Execution | None,
    rel_idx: dict[str, dict[str, dict[str, Any]]],
) -> tuple[Execution|None, dict[str, Any]|None]:
    if prev_activity is None or prev_execution is None:
        return None, None
    f = rel_idx.get(current["activity_id"], {}).get(prev_activity["activity_id"])
    if not isinstance(f, dict):
        return None, None
    delta = abs(current["_start_ts"] - prev_activity["_start_ts"])
    if delta > CONTEXT_CONTINUATION_MAX_SECONDS:
        return None, None
    if f.get("score", 0) < CONTEXT_SCORE_MIN or explicit_strong(f):
        return None, None
    if not context_compatible(current, prev_activity):
        return None, None
    ck = entity_keys(current)
    if ck and prev_execution.entity_keys and not ck.intersection(prev_execution.entity_keys):
        return None, None
    return prev_execution, {
        "mode":"CONTEXT","features":f,
        "member_activity_id":prev_activity["activity_id"],
        "delta_seconds":delta,
    }

def reconstruct_session(
    session_id: str,
    activities: list[dict[str, Any]],
    rel_idx: dict[str, dict[str, dict[str, Any]]],
) -> tuple[list[Execution], dict[str, Any]]:
    executions: list[Execution] = []
    execution_by_activity_id: dict[str, Execution] = {}
    activities_by_id = {a["activity_id"]: a for a in activities}
    counters = {"strong_join":0,"strong_ambiguous":0,"context_join":0,"new_execution":0,"unassigned":0}
    next_number = 1

    for i, activity in enumerate(activities):
        aid = activity["activity_id"]
        if is_system_unassigned(activity):
            counters["unassigned"] += 1
            continue

        chosen = None
        candidates = strong_candidates(activity, execution_by_activity_id, activities_by_id, rel_idx)
        chosen, _, status = choose_strong(candidates)
        if status == "AMBIGUOUS":
            counters["strong_ambiguous"] += 1
        if chosen is not None:
            counters["strong_join"] += 1
        if chosen is None and i > 0:
            chosen, _ = context_candidate(
                activity,
                activities[i-1],
                execution_by_activity_id.get(activities[i-1]["activity_id"]),
                rel_idx,
            )
            if chosen is not None:
                counters["context_join"] += 1

        if chosen is None:
            chosen = Execution(session_id, next_number, activity)
            next_number += 1
            executions.append(chosen)
            counters["new_execution"] += 1
        elif chosen.member_indices and chosen.member_indices[-1] != i - 1:
            chosen.close_contiguous_segment()

        chosen.add(i, activity)
        execution_by_activity_id[aid] = chosen

    for ex in executions:
        ex.finish()

    summary = {
        "session_id":session_id,
        "activities":len(activities),
        "logical_executions":len(executions),
        "unassigned_activities":counters["unassigned"],
        "unknown_activities":0,
        "assigned_activities":len(activities)-counters["unassigned"],
        "singleton_executions":sum(ex.member_count == 1 for ex in executions),
        "decision_counts":counters,
    }
    return executions, summary

def execution_record(execution: Execution, activities: list[dict[str, Any]]) -> dict[str, Any]:
    first, last = activities[execution.member_indices[0]], activities[execution.member_indices[-1]]
    segs = []
    for inds in execution.segments:
        if not inds: continue
        a, b = activities[inds[0]], activities[inds[-1]]
        segs.append({"start":a["start"],"end":b["end"],"activity_ids":[activities[i]["activity_id"] for i in inds]})
    return {
        "execution_id":execution.execution_id,
        "session_id":execution.session_id,
        "start":first["start"],
        "end":last["end"],
        "activity_ids":execution.activity_ids,
        "segments":segs,
    }

def build_segment_records(executions: list[Execution], activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_rows = []
    for ex in executions:
        ex.finish()
        for num, inds in enumerate(ex.segments, 1):
            if not inds:
                continue
            a, b = activities[inds[0]], activities[inds[-1]]
            if parse_timestamp(b["end"]) <= parse_timestamp(a["start"]):
                continue
            raw_rows.append({
                "session_id": ex.session_id,
                "start": a["start"],
                "end": b["end"],
                "label": ex.execution_id,
                "execution_id": ex.execution_id,
                "segment_number": num,
                "activity_count": len(inds),
            })

    raw_rows.sort(
        key=lambda r: (
            r["session_id"],
            parse_timestamp(r["start"]),
            parse_timestamp(r["end"]),
            r["execution_id"],
        )
    )

    # Final segment output must be non-overlapping even when two extracted
    # activities themselves overlap in time. Keep the earlier segment intact
    # and clip the later segment's start to the previous projected end. This
    # is only an output projection; execution membership remains unchanged.
    projected: list[dict[str, Any]] = []
    last_end_by_session: dict[str, datetime] = {}

    for row in raw_rows:
        start = parse_timestamp(row["start"])
        end = parse_timestamp(row["end"])
        previous_end = last_end_by_session.get(row["session_id"])

        if previous_end is not None and start < previous_end:
            start = previous_end
            row = dict(row)
            row["start"] = start.isoformat().replace("+00:00", "Z")

        if end <= start:
            continue

        projected.append(row)
        last_end_by_session[row["session_id"]] = end

    return projected

def self_check(by_session, executions_by_session, segments) -> None:
    for sid, activities in by_session.items():
        ids=[a["activity_id"] for a in activities]
        if len(ids)!=len(set(ids)): raise AssertionError(f"Duplicate activity IDs in {sid}")
        assigned=set()
        for ex in executions_by_session.get(sid,[]):
            if not ex.activity_ids: raise AssertionError(f"Empty execution in {sid}")
            for aid in ex.activity_ids:
                if aid in assigned: raise AssertionError(f"Activity assigned twice in {sid}: {aid}")
                assigned.add(aid)
        for a in activities:
            if is_system_unassigned(a): continue
            if a["activity_id"] not in assigned:
                raise AssertionError(f"Non-system activity left unassigned in {sid}: {a['activity_id']}")
    per=defaultdict(list)
    for s in segments:
        if parse_timestamp(s["end"]) <= parse_timestamp(s["start"]):
            raise AssertionError(f"Non-positive segment: {s}")
        per[s["session_id"]].append(s)
    for sid, rows in per.items():
        rows.sort(key=lambda x:parse_timestamp(x["start"]))
        for p,c in zip(rows,rows[1:]):
            if parse_timestamp(c["start"]) < parse_timestamp(p["end"]):
                raise AssertionError(f"Overlapping candidate segments in {sid}: {p} / {c}")

def write_jsonl(path: Path, rows: list[dict[str,Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8",newline="\n") as h:
        for r in rows: h.write(json.dumps(r,ensure_ascii=False)+"\n")

# ----- preflight -----
def _a(aid, sec, app="App", window="Window", tab="Tab", entity=None, typ="CLICK", layers=None):
    whole=int(sec); ms=int(round((sec-whole)*1000))
    return {
        "activity_id":aid,"session_id":"ses_preflight",
        "start":f"2026-01-01T00:00:{whole:02d}.{ms:03d}+00:00",
        "end":f"2026-01-01T00:00:{whole:02d}.{(ms+100)%1000:03d}+00:00",
        "type":typ,"app":app,"window":window,"browser_tab":tab,"browser_url":"https://example.test/page",
        "entities":[] if entity is None else [{"type":entity[0],"value":entity[1]}],
        "source_layers":["L2"] if layers is None else layers,
    }
def _f(**kw):
    d={"same_entity":False,"triggered_by":False,"same_window":False,"same_app":False,
       "same_browser_tab":False,"semantic_match":False,"close_in_time":True,
       "large_time_gap":False,"delta_seconds":1.0,"score":1,"strength":"WEAK",
       "evidence":[],"shared_entities":[]}
    d.update(kw); return d
def _run(activities, rels):
    by=validate_activities(activities)
    idx=build_relationship_index(rels)
    ex,s=reconstruct_session("ses_preflight",by["ses_preflight"],idx)
    seg=build_segment_records(ex,by["ses_preflight"])
    return ex,s,seg
def preflight():
    # 1 strong resume over interruption
    a,b,c=_a("a",0,entity=("CASE_ID","X")), _a("b",1), _a("c",40,entity=("CASE_ID","X"))
    rel=[{"activity_a":"a","activity_b":"c","features":_f(same_entity=True,score=5,strength="STRONG",shared_entities=[{"type":"CASE_ID","value":"x"}])}]
    ex,_,_=_run([a,b,c],rel); assert any(e.activity_ids==["a","c"] for e in ex)

    # 2 strict context joins immediate predecessor
    a,b=_a("a",0),_a("b",2)
    rel=[{"activity_a":"a","activity_b":"b","features":_f(same_window=True,same_app=True,close_in_time=True,score=5)}]
    ex,_,_=_run([a,b],rel); assert any(e.activity_ids==["a","b"] for e in ex)

    # 3 same window alone is insufficient
    a,b=_a("a",0,app="A",window="W"),_a("b",2,app="B",window="W")
    rel=[{"activity_a":"a","activity_b":"b","features":_f(same_window=True,score=3)}]
    ex,_,_=_run([a,b],rel); assert len(ex)==2

    # 4 same app + same tab is sufficient
    a,b=_a("a",0,app="Browser",window="W1",tab="T"),_a("b",2,app="Browser",window="W2",tab="T")
    rel=[{"activity_a":"a","activity_b":"b","features":_f(same_app=True,same_browser_tab=True,score=4)}]
    ex,_,_=_run([a,b],rel); assert any(e.activity_ids==["a","b"] for e in ex)

    # 5 context cannot jump over another activity
    a,b,c=_a("a",0),_a("b",2,app="Other",window="Other"),_a("c",4)
    rel=[{"activity_a":"a","activity_b":"c","features":_f(same_app=True,same_window=True,score=5)}]
    ex,_,_=_run([a,b,c],rel); assert not any(e.activity_ids==["a","c"] for e in ex)

    # 6 different explicit entity blocks context
    a,b=_a("a",0,entity=("CASE_ID","X")), _a("b",2,entity=("CASE_ID","Y"))
    rel=[{"activity_a":"a","activity_b":"b","features":_f(same_app=True,same_window=True,score=5)}]
    ex,_,_=_run([a,b],rel); assert len(ex)==2

    # 7 ambiguous strong links do not silently merge
    a=_a("a",0,entity=("CASE_ID","X")); b=_a("b",1,entity=("CASE_ID","Y")); c=_a("c",2,entity=("CASE_ID","X"))
    c["entities"].append({"type":"CASE_ID","value":"Y"})
    rel=[
        {"activity_a":"a","activity_b":"c","features":_f(same_entity=True,same_app=True,same_window=True,score=8,strength="STRONG",shared_entities=[{"type":"CASE_ID","value":"X"}])},
        {"activity_a":"b","activity_b":"c","features":_f(same_entity=True,same_app=True,same_window=True,score=8,strength="STRONG",shared_entities=[{"type":"CASE_ID","value":"Y"}])},
    ]
    ex,s,_=_run([a,b,c],rel); assert s["decision_counts"]["strong_ambiguous"]>=1 and len(ex)==3

    # 8 system activity is unassigned
    a,sysa,b=_a("a",0),_a("sys",1,typ="OTHER",layers=["SYSTEM"]),_a("b",2)
    ex,s,_=_run([a,sysa,b],[]); assert s["unassigned_activities"]==1 and len(ex)==2

    # 9 empty relationships are legal
    ex,_,_=_run([_a("a",0)],[]); assert len(ex)==1

    # 10 triggered_by can resume despite different entity
    a=_a("a",0,entity=("CASE_ID","X")); b=_a("b",1,entity=("CASE_ID","Y")); c=_a("c",2,entity=("CASE_ID","Z"))
    rel=[{"activity_a":"a","activity_b":"c","features":_f(triggered_by=True,score=5,strength="STRONG")}]
    ex,_,_=_run([a,b,c],rel); assert any(e.activity_ids==["a","c"] for e in ex)

    # 11 overlapping source activities are projected to non-overlapping output.
    x=_a("x",0,app="A",window="W1")
    y=_a("y",1,app="B",window="W2")
    # Force the two activities to span 3 seconds each.
    y["end"]="2026-01-01T00:00:04.000+00:00"
    by=validate_activities([x,y])
    exs,_=reconstruct_session("ses_preflight",by["ses_preflight"],build_relationship_index([]))
    segs=build_segment_records(exs,by["ses_preflight"])
    assert len(segs)==2
    assert parse_timestamp(segs[1]["start"]) >= parse_timestamp(segs[0]["end"])
    print("Preflight grouping self-test: PASS (11 cases)")

def build_parser():
    p=argparse.ArgumentParser(description="Reconstruct constrained logical process executions.")
    p.add_argument("--activities",required=True,type=Path)
    p.add_argument("--relationships",required=True,type=Path)
    p.add_argument("--output-dir",required=True,type=Path)
    return p

def main():
    preflight()
    args=build_parser().parse_args()
    try:
        ai=args.activities.resolve(); ri=args.relationships.resolve(); out=args.output_dir.resolve()
        if ai==ri: raise ValueError("Activities and relationships inputs must be different files.")
        if not ai.exists(): raise FileNotFoundError(ai)
        if not ri.exists(): raise FileNotFoundError(ri)
        out.mkdir(parents=True,exist_ok=True)
        outputs={out/"executions.jsonl",out/"segments_candidates.jsonl",out/"grouping_summary.json"}
        collision={ai,ri}.intersection(outputs)
        if collision: raise ValueError("Refusing to overwrite input: "+", ".join(map(str,sorted(collision))))
        act_records=load_jsonl(ai)
        rel_records=load_jsonl(ri,allow_empty=True)
        by=validate_activities(act_records)
        idx=build_relationship_index(rel_records)

        ex_by={}; summaries=[]; ex_rows=[]; seg_rows=[]
        for sid,acts in sorted(by.items()):
            exs,s=reconstruct_session(sid,acts,idx); ex_by[sid]=exs; summaries.append(s)
            ex_rows.extend(execution_record(e,acts) for e in exs)
            seg_rows.extend(build_segment_records(exs,acts))
        self_check(by,ex_by,seg_rows)

        totals=defaultdict(int)
        for s in summaries:
            for k,v in s["decision_counts"].items(): totals[k]+=v
        summary={
            "sessions":len(by),"activities":len(act_records),"logical_executions":len(ex_rows),
            "candidate_segments":len(seg_rows),
            "unassigned_activities":sum(s["unassigned_activities"] for s in summaries),
            "singleton_executions":sum(s["singleton_executions"] for s in summaries),
            "parameters":{
                "strong_bridge_max_seconds":STRONG_BRIDGE_MAX_SECONDS,
                "context_continuation_max_seconds":CONTEXT_CONTINUATION_MAX_SECONDS,
                "context_score_min":CONTEXT_SCORE_MIN,
                "strong_candidate_margin":STRONG_CANDIDATE_MARGIN,
            },
            "decision_totals":dict(sorted(totals.items())),
            "inputs":{"activities":str(ai),"relationships":str(ri)},
            "self_check":"PASS",
            "session_summaries":summaries,
        }
        write_jsonl(out/"executions.jsonl",ex_rows)
        write_jsonl(out/"segments_candidates.jsonl",seg_rows)
        (out/"grouping_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    except (OSError,ValueError,AssertionError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 1
    print("PROCESS RECONSTRUCTION v2")
    print("="*72)
    print(f"Sessions:                 {len(by)}")
    print(f"Activities:               {len(act_records)}")
    print(f"Logical executions:       {len(ex_rows)}")
    print(f"Candidate segments:       {len(seg_rows)}")
    print(f"UNASSIGNED activities:    {summary['unassigned_activities']}")
    print(f"Singleton executions:     {summary['singleton_executions']}")
    print("Decision totals:")
    for k,v in sorted(totals.items()): print(f"  {k:<22} {v:>8}")
    print("Parameters:")
    print(f"  strong bridge:          {STRONG_BRIDGE_MAX_SECONDS:.1f}s")
    print(f"  context continuation:   {CONTEXT_CONTINUATION_MAX_SECONDS:.1f}s")
    print(f"  context score minimum:  {CONTEXT_SCORE_MIN}")
    print(f"  strong margin:          {STRONG_CANDIDATE_MARGIN:.1f}")
    print("Self-check: PASS")
    print("Inputs untouched: YES")
    print(f"Wrote outputs to:        {out}")
    print(f"  executions:             {(out/'executions.jsonl').name}")
    print(f"  segments:               {(out/'segments_candidates.jsonl').name}")
    print(f"  summary:                {(out/'grouping_summary.json').name}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
