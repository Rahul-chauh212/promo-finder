"""The whole promo-finding process, step by step.

  Step 1  read scripts                          (code)
  Step 2  find hooks + cliffhangers per episode  (AI, batched; code checks every answer)
  Step 3  build promos from them                 (code: 20-60 s, hook in first 3 s, clean cuts)
  Step 4  stitched promos across moments         (AI proposes, code checks)
  Step 5  stranger test                          (a fresh AI with zero show context)
  Step 6  score, remove duplicates, rank         (code)
"""
from __future__ import annotations

import json
from pathlib import Path

from . import prompts
from .emotions import ALL_EMOTIONS, HIGH_AROUSAL_EMOTIONS, agreement, arousal, window_arousal
from .llm import LLM
from .parse import Episode, Line, fmt


# =============================================================== small helpers
def _clamp(v, lo=1, hi=5, default=3) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def length_fit(d: float, r: dict) -> float:
    if r["ideal_min"] <= d <= r["ideal_max"]:
        return 1.0
    if d < r["ideal_min"]:
        return 0.6 + 0.4 * max(0.0, d - r["min_seconds"]) / max(1, r["ideal_min"] - r["min_seconds"])
    return 0.6 + 0.4 * max(0.0, r["max_seconds"] - d) / max(1, r["max_seconds"] - r["ideal_max"])


def lines_in(ep: Episode, start: float, end: float) -> list[Line]:
    return [l for l in ep.lines if l.start < end - 0.05 and l.end > start + 0.05]


def clip_start(ep: Episode, start_line: Line, hook_line: Line, within: float) -> float:
    """Pick a clean start point so the hook lands in the first `within` seconds."""
    t_hook = hook_line.start
    t0 = start_line.start if 0 <= t_hook - start_line.start <= within else t_hook
    # snap back to the beginning of the camera shot if it is close
    for cam in ep.lines:
        if cam.kind == "camera" and cam.start <= t0 < cam.end:
            if t0 - cam.start <= 1.0 and t_hook - cam.start <= within:
                t0 = cam.start
            break
    # don't start in the middle of someone else's sentence
    for d in ep.lines:
        if d.kind == "dialogue" and d.start < t0 < d.end - 0.1:
            t0 = d.start if t_hook - d.start <= within else d.end
    # hook like "...husband and wife!" continues the line before: include that line if it fits in 3 s
    if hook_line.text.lstrip().startswith(("...", "…")):
        prev = [d for d in ep.lines if d.kind == "dialogue" and d.speaker == hook_line.speaker
                and d.end <= hook_line.start + 0.1 and hook_line.start - d.end <= 1.5]
        if prev and t_hook - prev[-1].start <= within:
            t0 = min(t0, prev[-1].start)
    return round(t0, 2)


def clip_end(ep: Episode, line: Line) -> tuple[float, str | None]:
    """End right after the cliffhanger line, letting the reaction shot land if it is short."""
    e = line.end
    flag = None
    for cam in ep.lines:
        if cam.kind == "camera" and cam.start < e <= cam.end:
            next_talk = any(d.kind == "dialogue" and e < d.start < cam.end for d in ep.lines)
            if cam.end - e <= 1.5 and not next_talk:
                e = cam.end
            break
    for d in ep.lines:
        if d.kind == "dialogue" and d.start < e - 0.1 < d.end - 0.1 and d.id != line.id:
            if d.end - e <= 2.0:
                e = d.end
            else:
                flag = f"cut lands in the middle of a line ({d.id})"
    return round(min(e, ep.duration or e), 2), flag


def seg_duration(segs: list[dict]) -> float:
    return round(sum(s["end"] - s["start"] for s in segs), 2)


def overlap(a: dict, b: dict) -> float:
    inter = 0.0
    for s in a["segments"]:
        for t in b["segments"]:
            if s["episode"] == t["episode"]:
                inter += max(0.0, min(s["end"], t["end"]) - max(s["start"], t["start"]))
    return inter / max(0.1, min(a["duration"], b["duration"]))


def story_lines(eps: list[Episode], before: int | None = None) -> str:
    return "\n".join(f"Ep {e.number}: {e.logline}" for e in eps
                     if e.logline and (before is None or e.number < before))


def episode_text(ep: Episode, include_camera: bool) -> str:
    rows = [f"=== EPISODE {ep.number} === (length {fmt(ep.duration)})",
            f"Logline: {ep.logline}"]
    rows += [l.short() for l in ep.lines if include_camera or l.kind != "camera"]
    return "\n".join(rows)


# ================================================== STEP 2: hooks & cliffhangers
def _mock_emotion(line: Line) -> str:
    t = " ".join(line.tags).lower() + " " + line.text.lower()
    for key, words in [("anger", ["gloat", "mock", "cruel", "venom", "smug", "scorn", "callous", "contempt"]),
                       ("shock", ["gasp", "stun", "shock", "horrif", "incredul"]),
                       ("fear", ["fear", "terrif", "panic", "desperat", "sinister", "ominous", "chill"]),
                       ("triumph", ["triumph", "exult", "defian", "resolute", "vengeful"]),
                       ("sadness", ["sad", "broken", "weep", "tear", "heartbroken", "crushed"])]:
        if any(w in t for w in words):
            return key
    return "curiosity"


def _mock_moments(batch: list[Episode], r: dict) -> dict:
    """Practice mode: pick moments with simple rules (no AI)."""
    out = []
    for ep in batch:
        cands = sorted([l for l in ep.lines if l.kind in ("dialogue", "action")],
                       key=lambda l: arousal(l), reverse=True)
        hooks, used = [], []
        for l in cands:
            if any(abs(l.start - u) < 8 for u in used):
                continue
            used.append(l.start)
            hooks.append({"start_line_id": l.id, "hook_line_id": l.id, "viewer_emotion": _mock_emotion(l),
                          "strength": 1 + round(4 * arousal(l)), "why": "rule-based: heated tags/words"})
            if len(hooks) >= r["hooks_per_episode"]:
                break
        cliffs = []
        talk = [l for l in ep.lines if l.kind in ("dialogue", "action")]
        scenes = sorted({l.scene for l in talk})
        for s in scenes:
            last = [l for l in talk if l.scene == s][-1]
            cliffs.append({"line_id": last.id, "open_question": "rule-based: end of scene",
                           "strength": 5 if s == scenes[-1] else 3})
        for l in talk:
            if len(cliffs) >= r["cliffhangers_per_episode"]:
                break
            if (l.text.endswith("?") or l.text.endswith("...")) and arousal(l) >= 0.6 \
                    and all(c["line_id"] != l.id for c in cliffs):
                cliffs.append({"line_id": l.id, "open_question": "rule-based: tense question", "strength": 3})
        out.append({"episode": ep.number, "hooks": hooks, "cliffhangers": cliffs})
    return {"episodes": out}


def find_moments(eps: list[Episode], llm: LLM, cfg: dict, log=print) -> tuple[dict, list[dict]]:
    r, b = cfg["promo_rules"], cfg["batching"]
    by_num = {e.number: e for e in eps}
    moments: dict[int, dict] = {e.number: {"hooks": [], "cliffhangers": []} for e in eps}
    rejected: list[dict] = []
    size = max(1, int(b["episodes_per_call"]))
    batches = [eps[i:i + size] for i in range(0, len(eps), size)]
    for bi, batch in enumerate(batches, 1):
        log(f"  Step 2: reading episodes {batch[0].number}-{batch[-1].number} ({bi}/{len(batches)})")
        user = prompts.moment_finder(
            story_lines(eps, before=batch[0].number),
            "\n\n".join(episode_text(e, b.get("include_camera_lines", False)) for e in batch),
            r["hooks_per_episode"], r["cliffhangers_per_episode"], ALL_EMOTIONS)
        data = llm.ask_json(f"moments_ep{batch[0].number:02d}-{batch[-1].number:02d}",
                            prompts.SYSTEM, user, mock=lambda bt=batch: _mock_moments(bt, r))
        for item in data.get("episodes", []):
            num = _clamp(item.get("episode"), 0, 10_000, -1)
            ep = by_num.get(num)
            if ep is None:
                rejected.append({"stage": "moments", "episode": item.get("episode"), "reason": "unknown episode"})
                continue
            for h in item.get("hooks", [])[: r["hooks_per_episode"]]:
                hl = ep.line(str(h.get("hook_line_id", "")))
                sl = ep.line(str(h.get("start_line_id", ""))) or hl
                if hl is None:
                    rejected.append({"stage": "hook", "episode": num, "item": h, "reason": "line ID not in script"})
                    continue
                note = None
                if not (0 <= hl.start - sl.start <= r["hook_within_seconds"]):
                    note = "start moved onto the hook (lead-in was longer than 3 s)"
                    sl = hl
                emo = str(h.get("viewer_emotion", "")).lower().strip()
                moments[num]["hooks"].append({
                    "episode": num, "start_line_id": sl.id, "hook_line_id": hl.id,
                    "hook_time": hl.start, "text": hl.text, "speaker": hl.speaker,
                    "emotion": emo if emo in ALL_EMOTIONS else "curiosity",
                    "strength": _clamp(h.get("strength")), "why": str(h.get("why", ""))[:200],
                    "code_arousal": arousal(hl), "note": note})
            for c in item.get("cliffhangers", [])[: r["cliffhangers_per_episode"]]:
                cl = ep.line(str(c.get("line_id", "")))
                if cl is None:
                    rejected.append({"stage": "cliffhanger", "episode": num, "item": c, "reason": "line ID not in script"})
                    continue
                moments[num]["cliffhangers"].append({
                    "episode": num, "line_id": cl.id, "time": cl.end, "text": cl.text, "speaker": cl.speaker,
                    "open_question": str(c.get("open_question", ""))[:200], "strength": _clamp(c.get("strength"))})
    return moments, rejected


# ======================================================== STEP 3: build promos
def build_candidates(eps: list[Episode], moments: dict, cfg: dict) -> list[dict]:
    r = cfg["promo_rules"]
    within = r["hook_within_seconds"]
    by_num = {e.number: e for e in eps}
    cands = []
    for ep in eps:
        m = moments.get(ep.number, {})
        nxt = by_num.get(ep.number + 1)
        for h in m.get("hooks", []):
            start = clip_start(ep, ep.line(h["start_line_id"]), ep.line(h["hook_line_id"]), within)
            # same episode
            for c in m.get("cliffhangers", []):
                cl = ep.line(c["line_id"])
                if cl.start < h["hook_time"] + 3:
                    continue
                end, flag = clip_end(ep, cl)
                segs = [{"episode": ep.number, "start": start, "end": end,
                         "start_line_id": h["start_line_id"], "end_line_id": cl.id}]
                d = seg_duration(segs)
                if r["min_seconds"] <= d <= r["max_seconds"]:
                    cands.append({"kind": "single", "segments": segs, "duration": d, "hook": h, "cliff": c,
                                  "flags": [flag] if flag else []})
            # end of this episode + start of the next one
            if r.get("allow_cross_episode") and nxt is not None:
                for c in moments.get(nxt.number, {}).get("cliffhangers", []):
                    cl = nxt.line(c["line_id"])
                    end, flag = clip_end(nxt, cl)
                    segs = [{"episode": ep.number, "start": start, "end": ep.duration,
                             "start_line_id": h["start_line_id"], "end_line_id": ep.lines[-1].id},
                            {"episode": nxt.number, "start": 0.0, "end": end,
                             "start_line_id": nxt.lines[0].id, "end_line_id": cl.id}]
                    d = seg_duration(segs)
                    if r["min_seconds"] <= d <= r["max_seconds"]:
                        cands.append({"kind": "cross-episode", "segments": segs, "duration": d, "hook": h,
                                      "cliff": c, "flags": ([flag] if flag else []) +
                                      ["joins two episodes: check the next episode doesn't open with a recap"]})
    for c in cands:
        c["pre_score"] = round(0.35 * c["hook"]["strength"] / 5 + 0.30 * c["cliff"]["strength"] / 5
                               + 0.20 * c["hook"]["code_arousal"] + 0.15 * length_fit(c["duration"], r), 4)
    return cands


def pick_diverse(cands: list[dict], n: int, max_overlap: float) -> list[dict]:
    """Keep the best ones; drop any that mostly repeat footage already kept."""
    kept: list[dict] = []
    used_hooks = set()
    for c in sorted(cands, key=lambda x: x.get("score", x["pre_score"]), reverse=True):
        hk = (c["hook"]["episode"], c["hook"]["hook_line_id"])
        if c["kind"] != "stitched" and hk in used_hooks:
            continue
        if any(overlap(c, k) > max_overlap for k in kept):
            continue
        kept.append(c)
        used_hooks.add(hk)
        if len(kept) >= n:
            break
    return kept


# ===================================================== STEP 4: stitched promos
def _mock_stitch(eps: list[Episode], hooks: list[dict], cliffs: list[dict], n: int) -> dict:
    by_num = {e.number: e for e in eps}
    out = []
    for h in hooks[:n]:
        c = next((c for c in cliffs if c["episode"] > h["episode"]), None)
        if not c:
            continue
        he, ce = by_num[h["episode"]], by_num[c["episode"]]
        hl = he.line(h["hook_line_id"])
        a_end = [l for l in he.lines if l.kind == "dialogue" and hl.start <= l.end <= hl.start + 12]
        cl = ce.line(c["line_id"])
        b_start = [l for l in ce.lines if l.kind == "dialogue" and cl.end - 14 <= l.start <= cl.start]
        if not a_end or not b_start:
            continue
        out.append({"title": "rule-based stitch", "segments": [
            {"start_line_id": h["start_line_id"], "end_line_id": a_end[-1].id},
            {"start_line_id": b_start[0].id, "end_line_id": cl.id}],
            "hook": h["text"], "cliffhanger": c["open_question"], "why": "rule-based pairing"})
    return {"promos": out}


def stitched_promos(eps: list[Episode], moments: dict, llm: LLM, cfg: dict, log=print) -> tuple[list[dict], list[dict]]:
    r = cfg["promo_rules"]
    n = int(r.get("stitched_promos", 0))
    if n <= 0:
        return [], []
    log("  Step 4: asking for stitched (multi-moment) promos")
    by_num = {e.number: e for e in eps}
    hooks = sorted([h for m in moments.values() for h in m["hooks"]],
                   key=lambda h: (h["strength"], h["code_arousal"]), reverse=True)[:40]
    cliffs = sorted([c for m in moments.values() for c in m["cliffhangers"]],
                    key=lambda c: c["strength"], reverse=True)[:40]
    hooks_text = "\n".join(f"{h['hook_line_id']} (start {h['start_line_id']}) | Ep {h['episode']} "
                           f"{fmt(h['hook_time'])} | {h['speaker'] or ''}: {h['text'][:140]} [{h['emotion']}]"
                           for h in hooks)
    cliffs_text = "\n".join(f"{c['line_id']} | Ep {c['episode']} {fmt(c['time'])} | {c['speaker'] or ''}: "
                            f"{c['text'][:140]} -> open question: {c['open_question']}" for c in cliffs)
    try:
        data = llm.ask_json("stitch", prompts.SYSTEM,
                            prompts.stitcher(story_lines(eps), hooks_text, cliffs_text, n,
                                             r["min_seconds"], r["max_seconds"]),
                            mock=lambda: _mock_stitch(eps, hooks, cliffs, n))
    except RuntimeError as e:
        # Stitching is a bonus: if it fails, finish the run with the normal promos.
        log(f"  Step 4 skipped ({e}). Continuing without stitched promos.")
        return [], [{"stage": "stitch", "reason": f"step skipped: {str(e)[:150]}"}]
    all_hooks = [h for m in moments.values() for h in m["hooks"]]
    all_cliffs = [c for m in moments.values() for c in m["cliffhangers"]]
    out, rejected = [], []
    for p in data.get("promos", [])[:n]:
        segs, bad = [], None
        for s in p.get("segments", [])[:3]:
            sid, eid = str(s.get("start_line_id", "")), str(s.get("end_line_id", ""))
            try:
                ep = by_num[int(sid[1:3])]
            except (ValueError, KeyError):
                bad = f"unknown line {sid}"
                break
            sl, el = ep.line(sid), ep.line(eid)
            if not sl or not el or el.episode != sl.episode or el.end <= sl.start:
                bad = f"bad piece {sid}->{eid}"
                break
            end, _ = clip_end(ep, el)
            segs.append({"episode": ep.number, "start": round(sl.start, 2), "end": end,
                         "start_line_id": sid, "end_line_id": eid})
        if bad or len(segs) < 2:
            rejected.append({"stage": "stitch", "item": p, "reason": bad or "needs 2+ pieces"})
            continue
        d = seg_duration(segs)
        if not (r["min_seconds"] <= d <= r["max_seconds"]):
            rejected.append({"stage": "stitch", "item": p, "reason": f"length {d:.1f}s outside {r['min_seconds']}-{r['max_seconds']}s"})
            continue
        s0, sl_ = segs[0], segs[-1]
        hook = next((h for h in all_hooks if h["episode"] == s0["episode"]
                     and s0["start"] - 0.5 <= h["hook_time"] <= s0["start"] + r["hook_within_seconds"]), None)
        if hook is None:
            rejected.append({"stage": "stitch", "item": p, "reason": "first 3 seconds do not contain a detected hook"})
            continue
        cliff = next((c for c in all_cliffs if c["episode"] == sl_["episode"] and abs(c["time"] - sl_["end"]) <= 2.0), None)
        flags = []
        if cliff is None:
            el = by_num[sl_["episode"]].line(sl_["end_line_id"])
            cliff = {"episode": sl_["episode"], "line_id": el.id, "time": el.end, "text": el.text,
                     "speaker": el.speaker, "open_question": str(p.get("cliffhanger", ""))[:200], "strength": 2}
            flags.append("ending was not one of the detected cliffhangers")
        out.append({"kind": "stitched", "segments": segs, "duration": d, "hook": hook, "cliff": cliff,
                    "flags": flags, "title": p.get("title", ""), "ai_why": p.get("why", ""),
                    "pre_score": 0.0})
    return out, rejected


# ======================================================= STEP 5: stranger test
def clip_script(eps_by_num: dict, promo: dict) -> str:
    rows, t_offset = [], 0.0
    for i, s in enumerate(promo["segments"]):
        if i:
            rows.append("--- CUT TO ---")
        ep = eps_by_num[s["episode"]]
        for l in lines_in(ep, s["start"], s["end"]):
            rel = max(0.0, l.start - s["start"]) + t_offset
            if l.kind == "dialogue":
                rows.append(f"[{rel:5.1f}s] {l.speaker}" + (f" ({', '.join(l.tags)})" if l.tags else "") + f': "{l.text}"')
            else:
                rows.append(f"[{rel:5.1f}s] {l.kind.upper()}: {l.text}")
        t_offset += s["end"] - s["start"]
    return "\n".join(rows)


def _mock_stranger(batch: list[dict], eps_by_num: dict) -> dict:
    out = []
    for p in batch:
        s0 = p["segments"][0]
        ep = eps_by_num[s0["episode"]]
        g = window_arousal(ep.lines, s0["start"], s0["start"] + 3)
        out.append({"id": p["id"], "what_happens": "(practice mode: no AI)", "first_3_seconds": p["hook"]["text"],
                    "grab": 1 + round(4 * g), "makes_sense_alone": 3,
                    "need_to_know_next": 1 + round(4 * p["cliff"]["strength"] / 5),
                    "open_question": p["cliff"].get("open_question", ""), "confusing": "unknown in practice mode",
                    "why_it_works": f"opens on '{p['hook']['text'][:60]}'"})
    return {"clips": out}


def stranger_test(eps: list[Episode], promos: list[dict], llm: LLM, cfg: dict, log=print) -> None:
    by_num = {e.number: e for e in eps}
    size = max(1, int(cfg["batching"]["promos_per_stranger_call"]))
    for i in range(0, len(promos), size):
        batch = promos[i:i + size]
        log(f"  Step 5: stranger test on promos {i + 1}-{i + len(batch)} of {len(promos)}")
        text = "\n\n".join(f"### CLIP {p['id']} ({p['duration']:.0f} seconds)\n{clip_script(by_num, p)}" for p in batch)
        data = llm.ask_json(f"stranger_{i // size + 1:02d}", prompts.STRANGER_SYSTEM, prompts.stranger_test(text),
                            mock=lambda bt=batch: _mock_stranger(bt, by_num))
        answers = {str(c.get("id")): c for c in data.get("clips", [])}
        for p in batch:
            a = answers.get(p["id"])
            if a is None:
                p["flags"].append("stranger test returned no answer for this clip")
                a = {"grab": 3, "makes_sense_alone": 3, "need_to_know_next": 3}
            p["stranger"] = {k: a.get(k) for k in ("what_happens", "first_3_seconds", "grab", "makes_sense_alone",
                                                   "need_to_know_next", "open_question", "confusing", "why_it_works")}
            for k in ("grab", "makes_sense_alone", "need_to_know_next"):
                p["stranger"][k] = _clamp(p["stranger"][k])


# =================================================== STEP 6: score and rank
def score(promos: list[dict], cfg: dict) -> None:
    w, r = cfg["weights"], cfg["promo_rules"]
    for p in promos:
        h, c, s = p["hook"], p["cliff"], p["stranger"]
        hook = 0.5 * h["strength"] / 5 + 0.5 * (s["grab"] - 1) / 4
        cliff = 0.5 * c["strength"] / 5 + 0.5 * (s["need_to_know_next"] - 1) / 4
        alone = (s["makes_sense_alone"] - 1) / 4
        emo, emo_flag = agreement(h["emotion"], h["code_arousal"])
        fit = length_fit(p["duration"], r)
        p["parts"] = {"hook": round(hook, 3), "cliffhanger": round(cliff, 3), "stands_alone": round(alone, 3),
                      "emotion_check": round(emo, 3), "length_fit": round(fit, 3)}
        p["score"] = round(100 * (w["hook"] * hook + w["cliffhanger"] * cliff + w["stands_alone"] * alone
                                  + w["emotion_check"] * emo + w["length_fit"] * fit), 1)
        if emo_flag:
            p["flags"].append(emo_flag)
        if s["makes_sense_alone"] <= 2:
            p["flags"].append(f"stranger was confused: {s.get('confusing') or 'unclear'}")
        if s["grab"] <= 2:
            p["flags"].append("weak first 3 seconds (stranger would scroll past)")
        if s["need_to_know_next"] <= 3:
            p["flags"].append("ending may resolve the story instead of leaving a strong open question")
        first_seg = p["segments"][0]
        if h["text"].lstrip().startswith(("...", "…")) and h["hook_time"] - first_seg["start"] < 0.5:
            p["flags"].append("hook starts mid-sentence (the line begins with '...')")
        if h.get("note"):
            p["flags"].append(h["note"])


def rank(promos: list[dict], cfg: dict) -> list[dict]:
    r = cfg["promo_rules"]
    ordered = pick_diverse(promos, len(promos), r["max_overlap"])
    # variety: at most N promos per episode before the rest
    count: dict[int, int] = {}
    first, later = [], []
    for p in sorted(ordered, key=lambda x: (-x["score"], x["segments"][0]["episode"])):
        e = p["segments"][0]["episode"]
        count[e] = count.get(e, 0) + 1
        (first if count[e] <= r["max_per_episode_in_top"] else later).append(p)
    final = first + later
    for i, p in enumerate(final, 1):
        p["rank"] = i
    return final


# ================================================================ orchestrator
def run(eps: list[Episode], cfg: dict, llm: LLM, run_dir: Path, log=print) -> dict:
    r = cfg["promo_rules"]
    log(f"Read {len(eps)} episodes. Using AI: {llm.name} / {llm.model or 'rules only'}")
    moments, rejected = find_moments(eps, llm, cfg, log)
    n_h = sum(len(m["hooks"]) for m in moments.values())
    n_c = sum(len(m["cliffhangers"]) for m in moments.values())
    log(f"  found {n_h} hooks and {n_c} cliffhangers ({len(rejected)} AI answers rejected)")

    log("  Step 3: building promos (20-60 s, hook in first 3 s)")
    cands = build_candidates(eps, moments, cfg)
    log(f"  {len(cands)} possible clips; keeping the best {r['candidates_to_test']} different ones")
    chosen = pick_diverse(cands, int(r["candidates_to_test"]), r["max_overlap"])

    stitched, rej2 = stitched_promos(eps, moments, llm, cfg, log)
    rejected += rej2
    promos = chosen + stitched
    for i, p in enumerate(promos, 1):
        p["id"] = f"P{i:02d}"

    stranger_test(eps, promos, llm, cfg, log)
    score(promos, cfg)
    final = rank(promos, cfg)
    log(f"Done: {len(final)} ranked promos.")
    result = {"settings": {"provider": llm.name, "model": llm.model, "episodes": [e.number for e in eps],
                           "rules": r, "weights": cfg["weights"]},
              "usage": llm.usage(), "promos": final, "moments": {str(k): v for k, v in moments.items()},
              "rejected": rejected, "candidates_considered": len(cands)}
    (run_dir / "promos.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return result
