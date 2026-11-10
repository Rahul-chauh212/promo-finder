"""Turn the results into files people can read: report.md, promos.csv, review_sheet.csv."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .parse import fmt


def seg_text(p: dict) -> str:
    return " + ".join(f"Ep {s['episode']} {fmt(s['start'])}-{fmt(s['end'])}" for s in p["segments"])


def why_line(p: dict) -> str:
    s = p.get("stranger", {})
    return (s.get("why_it_works") or p.get("ai_why") or p["hook"].get("why") or "").strip()


def write_csv(result: dict, run_dir: Path) -> None:
    with open(run_dir / "promos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "score", "type", "length_s", "segments (in order)", "hook (first 3 s)",
                    "hook emotion", "cliffhanger (last line)", "open question", "why it works",
                    "stranger: grab", "stranger: makes sense", "stranger: need next", "flags"])
        for p in result["promos"]:
            s = p["stranger"]
            w.writerow([p["rank"], p["id"], p["score"], p["kind"], p["duration"], seg_text(p),
                        p["hook"]["text"], p["hook"]["emotion"], p["cliff"]["text"],
                        s.get("open_question") or p["cliff"].get("open_question"), why_line(p),
                        s["grab"], s["makes_sense_alone"], s["need_to_know_next"], " | ".join(p["flags"])])
    with open(run_dir / "review_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "segments", "hook", "cliffhanger", "your_verdict (good/ok/bad)", "your_note"])
        for p in result["promos"]:
            w.writerow([p["rank"], p["id"], seg_text(p), p["hook"]["text"], p["cliff"]["text"], "", ""])


def write_report(result: dict, run_dir: Path, seconds: float) -> None:
    P = result["promos"]
    u = result["usage"]
    eps = result["settings"]["episodes"]
    L: list[str] = []
    L.append("# Promo Finder: results\n")
    L.append(f"- Episodes read: {len(eps)} ({min(eps)}-{max(eps)})" if eps else "- Episodes read: 0")
    L.append(f"- AI used: **{u['provider']}** `{u['model'] or 'rules only (practice mode)'}`")
    L.append(f"- AI requests: {u['api_calls']} new, {u['cache_hits']} from cache | tokens in/out: "
             f"{u['tokens_in']:,}/{u['tokens_out']:,} | time: {seconds:.0f}s")
    L.append(f"- Possible clips considered: {result['candidates_considered']} -> ranked promos: {len(P)}\n")
    if u["provider"] == "mock":
        L.append("> **Practice mode.** No AI was used; picks come from simple rules. Use a real model for real results.\n")

    L.append("## Post these first\n")
    for p in P[:5]:
        s = p["stranger"]
        early = " It comes from early in the show, so it sells the premise without spoilers." \
            if p["segments"][0]["episode"] <= 5 else ""
        L.append(f"**{p['rank']}. {p['id']}** (score {p['score']}): opens on *{p['hook']['emotion']}* "
                 f"(\"{p['hook']['text'][:90]}\"). A stranger would stop ({s['grab']}/5), understood it "
                 f"({s['makes_sense_alone']}/5) and wants the next part ({s['need_to_know_next']}/5). "
                 f"Leaves the viewer asking: *{s.get('open_question') or p['cliff'].get('open_question')}*.{early}\n")

    L.append("## All promos, ranked\n")
    L.append("| # | id | score | length | segments (in order) | hook | cliffhanger | why it works |")
    L.append("|---|---|---|---|---|---|---|---|")
    for p in P:
        L.append(f"| {p['rank']} | {p['id']} | {p['score']} | {p['duration']:.0f}s | {seg_text(p)} | "
                 f"{p['hook']['text'][:70]} | {p['cliff']['text'][:70]} | {why_line(p)[:90]} |".replace("\n", " "))

    L.append("\n## Details\n")
    for p in P:
        s, h, c = p["stranger"], p["hook"], p["cliff"]
        L.append(f"### {p['rank']}. {p['id']}: {p['kind']}, {p['duration']:.1f}s, score {p['score']}")
        for i, seg in enumerate(p["segments"], 1):
            L.append(f"- Segment {i}: **Episode {seg['episode']}, {fmt(seg['start'])} -> {fmt(seg['end'])}** "
                     f"(lines {seg['start_line_id']} to {seg['end_line_id']})")
        L.append(f"- **Hook** (Ep {h['episode']} at {fmt(h['hook_time'])}, {h['emotion']}, strength {h['strength']}/5, "
                 f"script-energy {h['code_arousal']:.2f}): {h.get('speaker') or ''} \"{h['text']}\"")
        L.append(f"- **Cliffhanger** (Ep {c['episode']} at {fmt(c['time'])}, strength {c['strength']}/5): "
                 f"{c.get('speaker') or ''} \"{c['text']}\". Open question: {s.get('open_question') or c.get('open_question')}")
        L.append(f"- **Why it works:** {why_line(p)}")
        L.append(f"- Stranger test: \"{s.get('what_happens')}\" | grab {s['grab']}/5, makes sense {s['makes_sense_alone']}/5, "
                 f"need next {s['need_to_know_next']}/5 | confusing: {s.get('confusing')}")
        L.append(f"- Score parts: " + ", ".join(f"{k} {v:.2f}" for k, v in p["parts"].items()))
        if p["flags"]:
            L.append("- ⚠️ " + "; ".join(p["flags"]))
        L.append("")

    L.append("## Quality check: where the tool may be picking badly\n")
    flags = Counter(f.split(":")[0].split("(")[0].strip() for p in P for f in p["flags"])
    if flags:
        L.append("Warnings raised on the ranked promos:\n")
        for k, v in flags.most_common():
            L.append(f"- {v} x {k}")
    else:
        L.append("No automatic warnings were raised.")
    rej = result["rejected"]
    L.append(f"\nAI answers thrown out by the code checks: **{len(rej)}**")
    for k, v in Counter(r["reason"] for r in rej).most_common():
        L.append(f"- {v} x {k}")
    L.append("\nKnown blind spots (always true): the tool reads the script, not the video. It cannot see acting, "
             "music or how good a shot actually looks. Scores are the AI's judgement plus simple rules, so run "
             "`evaluate.py` against a human answer key to measure accuracy.")
    (run_dir / "report.md").write_text("\n".join(L), encoding="utf-8")
