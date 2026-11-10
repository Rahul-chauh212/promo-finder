"""Test the real AI path without spending any requests.

We pretend to be an OpenAI-style server and give back answers, including some
deliberately WRONG ones (made-up line IDs, a lead-in that is too long, a stitched
promo that is too long), to check the code catches them.

Run:  python -m tests.test_with_fake_ai
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

import yaml

from promo_finder import pipeline, report
from promo_finder.llm import LLM
from promo_finder.parse import load_folder

ROOT = Path(__file__).resolve().parents[1]

MOMENTS = {"episodes": [
    {"episode": 1,
     "hooks": [
         {"start_line_id": "E01-025", "hook_line_id": "E01-027", "viewer_emotion": "anger", "strength": 5, "why": "sister steals groom"},
         {"start_line_id": "E01-008", "hook_line_id": "E01-008", "viewer_emotion": "shock", "strength": 4, "why": "turn around"},
         {"start_line_id": "E01-001", "hook_line_id": "E01-031", "viewer_emotion": "anger", "strength": 4, "why": "lead-in too long"},
         {"start_line_id": "E01-999", "hook_line_id": "E01-999", "viewer_emotion": "anger", "strength": 5, "why": "made-up ID"}],
     "cliffhangers": [
         {"line_id": "E01-055", "open_question": "How long has this been going on?", "strength": 4},
         {"line_id": "E01-095", "open_question": "What will Juliana do now?", "strength": 5}]},
    {"episode": 30,
     "hooks": [{"start_line_id": "E30-008", "hook_line_id": "E30-008", "viewer_emotion": "fear", "strength": 4, "why": "rat in the cellar"}],
     "cliffhangers": [{"line_id": "E30-070", "open_question": "Will she be hanged as a witch?", "strength": 5}]},
]}

STITCH = {"promos": [
    {"title": "jilted to witch", "segments": [{"start_line_id": "E01-027", "end_line_id": "E01-032"},
                                              {"start_line_id": "E30-063", "end_line_id": "E30-064"}],
     "hook": "sister: he is marrying me", "cliffhanger": "will she hang?", "why": "fall from bride to witch"},
    {"title": "too long", "segments": [{"start_line_id": "E01-001", "end_line_id": "E01-090"},
                                       {"start_line_id": "E30-001", "end_line_id": "E30-070"}],
     "hook": "x", "cliffhanger": "y", "why": "should be rejected"}]}


def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
    user = json["messages"][-1]["content"]
    if "STRONGEST HOOK MOMENTS" in user:
        body = STITCH
    elif "Here are several clips" in user:
        ids = [l.split()[2] for l in user.splitlines() if l.startswith("### CLIP")]
        body = {"clips": [{"id": i, "what_happens": "a bride is dumped at the altar", "first_3_seconds": "smug sister",
                           "grab": 4, "makes_sense_alone": 4 if n % 2 == 0 else 2, "need_to_know_next": 4,
                           "open_question": "what will she do?", "confusing": "who the older woman is",
                           "why_it_works": "public betrayal + smug villain"} for n, i in enumerate(ids)]}
    else:
        body = MOMENTS
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {"choices": [{"message": {"content": __import__("json").dumps(body)}}],
                              "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}
    return resp


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["ai"]["seconds_between_calls"] = 0
    eps = [e for e in load_folder(ROOT / "episodes") if e.number in (1, 30)]
    with tempfile.TemporaryDirectory() as tmp, mock.patch("promo_finder.llm.requests.post", side_effect=fake_post):
        run_dir = Path(tmp)
        llm = LLM("fake", {"type": "openai", "base_url": "http://fake", "model": "fake-1", "key_env": ""},
                  cfg["ai"], run_dir, cache_dir=run_dir / "cache")
        res = pipeline.run(eps, cfg, llm, run_dir, log=lambda *_: None)
        report.write_csv(res, run_dir)
        report.write_report(res, run_dir, 1)

        reasons = [r["reason"] for r in res["rejected"]]
        assert "line ID not in script" in reasons, reasons
        assert any("outside" in r for r in reasons), reasons
        hooks = res["moments"]["1"]["hooks"]
        moved = [h for h in hooks if h["hook_line_id"] == "E01-031"][0]
        assert moved["start_line_id"] == "E01-031", "long lead-in should be moved onto the hook"
        for p in res["promos"]:
            assert 20 <= p["duration"] <= 60, p["duration"]
            s0 = p["segments"][0]
            assert p["hook"]["hook_time"] - s0["start"] <= 3.0 + 1e-6, (p["id"], p["hook"]["hook_time"], s0["start"])
        assert any(p["kind"] == "stitched" for p in res["promos"]), "valid stitched promo should survive"
        assert any("confused" in f for p in res["promos"] for f in p["flags"])
        print(f"OK: {len(res['promos'])} promos, {len(res['rejected'])} bad AI answers caught: {sorted(set(reasons))}")
        print((run_dir / "report.md").read_text(encoding="utf-8")[:1800])


if __name__ == "__main__":
    main()
