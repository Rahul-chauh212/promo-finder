"""Check the tool against YOUR answers (the "answer key").

  python evaluate.py --run outputs/run_xxx --key labels/answer_key.csv
  python evaluate.py --run outputs/run_xxx --key labels/answer_key.csv --review outputs/run_xxx/review_sheet.csv

Answer key format (one row per moment you picked by reading the episode):
  episode,type,time,note
  1,hook,00:39,"sister: Because he is marrying me"
  1,cliffhanger,02:17,"face hardens, cut to black"

What it measures (in plain words):
  * Found-rate: of the hooks/cliffhangers YOU picked, how many did the tool also find (within 3 s)?
  * Hit-rate:   of the hooks the tool picked in the episodes you labelled, how many match yours?
  * In-promo:   how many of your moments ended up inside the final ranked promos?
  * If you filled the review sheet: how many of the top 10 promos you called "good".
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

TOL = 3.0


def to_sec(s: str) -> float:
    s = s.strip()
    if ":" in s:
        m, sec = s.split(":")
        return int(m) * 60 + float(sec)
    return float(s)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--key", default="labels/answer_key.csv")
    ap.add_argument("--review")
    a = ap.parse_args(argv)
    run = Path(a.run)
    res = json.loads((run / "promos.json").read_text(encoding="utf-8"))
    key = [r for r in csv.DictReader(open(a.key, encoding="utf-8")) if r.get("episode", "").strip()]
    labelled = {int(r["episode"]) for r in key}

    tool_hooks = [h for m in res["moments"].values() for h in m["hooks"]]
    tool_cliffs = [c for m in res["moments"].values() for c in m["cliffhangers"]]
    promos = res["promos"]

    def near(ep, t, items, tkey, tol=TOL):
        return any(i["episode"] == ep and abs(i[tkey] - t) <= tol for i in items)

    def in_promo(ep, t):
        return any(s["episode"] == ep and s["start"] - TOL <= t <= s["end"] + TOL for p in promos for s in p["segments"])

    out = ["# Evaluation against the answer key\n", f"Episodes you labelled: {sorted(labelled)}\n"]
    for typ, items, tkey in (("hook", tool_hooks, "hook_time"), ("cliffhanger", tool_cliffs, "time")):
        mine = [r for r in key if r["type"].strip().lower() == typ]
        if not mine:
            continue
        found = [r for r in mine if near(int(r["episode"]), to_sec(r["time"]), items, tkey)]
        inp = [r for r in mine if in_promo(int(r["episode"]), to_sec(r["time"]))]
        tool_in = [i for i in items if i["episode"] in labelled]
        hits = [i for i in tool_in if any(int(r["episode"]) == i["episode"] and abs(to_sec(r["time"]) - i[tkey]) <= TOL
                                          for r in mine)]
        out.append(f"## {typ.title()}s")
        out.append(f"- Found-rate: tool found **{len(found)}/{len(mine)}** of your {typ}s ({100*len(found)/len(mine):.0f}%)")
        near10 = [r for r in mine if near(int(r["episode"]), to_sec(r["time"]), items, tkey, tol=10)]
        out.append(f"- Near-miss rate (within 10 s, same moment of the scene): **{len(near10)}/{len(mine)}**")
        if tool_in:
            out.append(f"- Hit-rate: **{len(hits)}/{len(tool_in)}** of the tool's {typ}s in those episodes match yours "
                       f"({100*len(hits)/len(tool_in):.0f}%). The rest are either new finds or bad picks: check them.")
        out.append(f"- Inside final promos: {len(inp)}/{len(mine)}")
        missed = [r for r in mine if r not in found]
        if missed:
            out.append("- Missed (the tool's blind spots):")
            out += [f"  - Ep {r['episode']} {r['time']}: {r.get('note', '')}" for r in missed]
        out.append("")

    if a.review and Path(a.review).exists():
        rows = list(csv.DictReader(open(a.review, encoding="utf-8")))
        col = next((c for c in rows[0] if c.startswith("your_verdict")), None) if rows else None
        rated = [r for r in rows if col and r[col].strip()]
        if rated:
            top = [r for r in rated if int(r["rank"]) <= 10]
            good = [r for r in top if r[col].strip().lower() == "good"]
            bad = [r for r in rated if r[col].strip().lower() == "bad"]
            out.append("## Your review of the ranked promos")
            out.append(f"- Top 10 rated 'good': **{len(good)}/{len(top)}**")
            out.append(f"- Rated 'bad' anywhere: {len(bad)}")
            out += [f"  - #{r['rank']} {r['id']}: {r.get('your_note', '')}" for r in bad]

    text = "\n".join(out)
    (run / "evaluation.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
