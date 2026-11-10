"""Simple web page for the promo finder.

  streamlit run app.py

Upload episode .txt files, pick an AI, press Run, read the ranked promos.
Works on Streamlit Community Cloud too (put keys in the app's Secrets).
Episode files are never stored in the repo: they are uploaded each time.
"""
from __future__ import annotations

import io
import os
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from promo_finder import pipeline, report
from promo_finder.llm import LLM, load_env
from promo_finder.parse import load_folder

ROOT = Path(__file__).parent
load_env(ROOT / ".env")
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

st.set_page_config(page_title="Promo Finder", layout="wide")
st.title("Promo Finder")
st.caption("Reads microdrama screenplays and finds 20-60 s promos that open on a hook and end on a cliffhanger.")

with st.sidebar:
    st.header("AI settings")
    names = list(cfg["providers"].keys())
    provider = st.selectbox("Provider", names, index=names.index(cfg["provider"]) if cfg["provider"] in names else 0,
                            help="'mock' = practice mode with simple rules, no AI and no key")
    pcfg = dict(cfg["providers"][provider])
    if pcfg.get("type") != "mock":
        pcfg["model"] = st.text_input("Model", pcfg.get("model", ""))
        env = pcfg.get("key_env", "")
        secret = ""
        try:
            secret = st.secrets.get(env, "") if env else ""
        except Exception:  # noqa: BLE001  (no secrets file locally)
            secret = ""
        key = st.text_input(f"API key ({env})", value="", type="password",
                            help="Left empty = use .env file or app secrets") or secret or os.environ.get(env, "")
    else:
        key = None
    st.header("Rules")
    cfg["promo_rules"]["candidates_to_test"] = st.slider("Promos to test and rank", 5, 60,
                                                         cfg["promo_rules"]["candidates_to_test"])
    cfg["batching"]["episodes_per_call"] = st.slider("Episodes per AI request", 1, 10,
                                                     cfg["batching"]["episodes_per_call"],
                                                     help="Higher = fewer requests (free tiers allow few per day)")

files = st.file_uploader("Episode screenplay files (.txt)", type=["txt"], accept_multiple_files=True)
use_local = st.checkbox("Use the local 'episodes' folder instead", value=not files and (ROOT / "episodes").exists())

if st.button("Find promos", type="primary"):
    with tempfile.TemporaryDirectory() as tmp:
        folder = ROOT / "episodes" if use_local else Path(tmp)
        if not use_local:
            for f in files or []:
                (folder / f.name).write_bytes(f.getvalue())
        eps = load_folder(folder)
        if not eps:
            st.error("No episodes found. Upload .txt screenplay files.")
            st.stop()
        run_dir = ROOT / "outputs" / f"run_{datetime.now():%Y%m%d_%H%M%S}_{provider}"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            llm = LLM(provider, pcfg, cfg["ai"], run_dir, cache_dir=ROOT / ".cache", api_key=key)
        except RuntimeError as e:
            st.error(str(e))
            st.stop()
        box = st.status("Working...", expanded=True)
        t = time.time()
        try:
            result = pipeline.run(eps, cfg, llm, run_dir, log=box.write)
        except Exception as e:  # noqa: BLE001
            box.update(label="Failed", state="error")
            st.exception(e)
            st.stop()
        report.write_csv(result, run_dir)
        report.write_report(result, run_dir, time.time() - t)
        box.update(label=f"Done in {time.time() - t:.0f}s", state="complete")
        st.session_state["run_dir"] = str(run_dir)

if "run_dir" in st.session_state:
    run_dir = Path(st.session_state["run_dir"])
    df = pd.read_csv(run_dir / "promos.csv")
    st.subheader("Ranked promos")
    st.dataframe(df, width="stretch", hide_index=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in run_dir.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(run_dir))
    c1, c2, c3 = st.columns(3)
    c1.download_button("Download promos.csv", (run_dir / "promos.csv").read_bytes(), "promos.csv")
    c2.download_button("Download report.md", (run_dir / "report.md").read_bytes(), "report.md")
    c3.download_button("Download everything (raw outputs)", buf.getvalue(), f"{run_dir.name}.zip")
    with st.expander("Full report", expanded=False):
        st.markdown((run_dir / "report.md").read_text(encoding="utf-8"))
