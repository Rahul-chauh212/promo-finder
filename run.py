"""Run the promo finder from the terminal.

  python run.py                          # uses config.yaml (provider + episodes folder)
  python run.py --provider mock          # practice mode, no AI, no key
  python run.py --provider groq --model llama-3.3-70b-versatile
  python run.py --episodes episodes --only 1-10   # just episodes 1 to 10
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import yaml

from promo_finder import pipeline, report
from promo_finder.llm import LLM, load_env
from promo_finder.parse import load_folder


def parse_range(s: str | None):
    if not s:
        return None
    a, _, b = s.partition("-")
    return int(a), int(b or a)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find the best promos in microdrama screenplays.")
    ap.add_argument("--episodes", default="episodes", help="folder with episode .txt files")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--provider", help="override provider in config (gemini, groq, anthropic, mock, ...)")
    ap.add_argument("--model", help="override the model name")
    ap.add_argument("--only", help="episode range, e.g. 1-10")
    ap.add_argument("--out", default="outputs")
    a = ap.parse_args(argv)

    load_env()
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    provider = a.provider or cfg["provider"]
    pcfg = dict(cfg["providers"][provider])
    if a.model:
        pcfg["model"] = a.model

    eps = load_folder(a.episodes)
    rng = parse_range(a.only)
    if rng:
        eps = [e for e in eps if rng[0] <= e.number <= rng[1]]
    if not eps:
        raise SystemExit(f"No episode .txt files found in '{a.episodes}'.")

    run_dir = Path(a.out) / f"run_{datetime.now():%Y%m%d_%H%M%S}_{provider}"
    run_dir.mkdir(parents=True, exist_ok=True)
    llm = LLM(provider, pcfg, cfg["ai"], run_dir)
    t = time.time()
    result = pipeline.run(eps, cfg, llm, run_dir)
    report.write_csv(result, run_dir)
    report.write_report(result, run_dir, time.time() - t)
    print(f"\nResults saved in: {run_dir}/")
    print("  report.md        <- read this first")
    print("  promos.csv       <- the ranked list (opens in Excel / Google Sheets)")
    print("  review_sheet.csv <- mark each promo good/ok/bad, then run evaluate.py")
    print("  raw_ai/          <- every AI question and answer, unedited")


if __name__ == "__main__":
    main()
