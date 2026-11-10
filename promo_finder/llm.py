"""The AI connector. One small class that can talk to any model.

Swapping models = change one word in config.yaml (or pick in the web app).
Supported out of the box:
  * any "OpenAI-style" service: Gemini, Groq, OpenRouter, OpenAI, local Ollama
  * Anthropic (Claude)
  * mock: a no-AI practice mode that uses simple rules, so you can test the
    whole tool for free and offline.

Every answer is:
  * saved raw to outputs/<run>/raw_ai/   (the brief asks for unedited outputs)
  * cached in .cache/  (re-running the same thing costs zero requests)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import requests


def load_env(path: str | Path = ".env") -> None:
    """Tiny .env reader: KEY=value lines -> environment variables."""
    p = Path(path)
    if not p.exists():
        return
    for row in p.read_text(encoding="utf-8").splitlines():
        row = row.strip()
        if not row or row.startswith("#") or "=" not in row:
            continue
        k, v = row.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply (handles ```json fences)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            return json.loads(t[a:b + 1])
        raise


class LLM:
    def __init__(self, provider_name: str, provider_cfg: dict, settings: dict,
                 run_dir: Path, cache_dir: Path = Path(".cache"), api_key: str | None = None):
        self.name = provider_name
        self.cfg = provider_cfg
        self.kind = provider_cfg.get("type", "openai")
        self.model = provider_cfg.get("model", "")
        self.settings = settings
        self.raw_dir = Path(run_dir) / "raw_ai"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        env = provider_cfg.get("key_env") or ""
        self.api_key = api_key or (os.environ.get(env, "") if env else "")
        self.calls = 0
        self.cached = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._last_call = 0.0
        if self.kind != "mock" and env and not self.api_key:
            raise RuntimeError(
                f"No API key found. Put {env}=your_key in the .env file "
                f"(or choose provider 'mock' to practise without AI).")

    # ------------------------------------------------------------------ public
    def ask_json(self, task: str, system: str, user: str,
                 mock: Callable[[], dict] | None = None) -> dict:
        """Send one question, get back a filled-in form (a Python dict)."""
        if self.kind == "mock":
            out = mock() if mock else {}
            self._save(task, system, user, json.dumps(out, indent=2), cached=False)
            return out

        key = hashlib.sha256(f"{self.name}|{self.model}|{system}|{user}".encode()).hexdigest()[:24]
        cpath = self.cache_dir / f"{key}.json"
        if cpath.exists():
            self.cached += 1
            text = json.loads(cpath.read_text(encoding="utf-8"))["text"]
            self._save(task, system, user, text, cached=True)
            return extract_json(text)

        last_err = None
        for attempt in range(2):  # second try: remind it to send valid JSON
            u = user if attempt == 0 else user + "\n\nIMPORTANT: reply with ONE valid JSON object only."
            text = self._call(system, u)
            self._save(task, system, u, text, cached=False)
            try:
                data = extract_json(text)
                cpath.write_text(json.dumps({"text": text}), encoding="utf-8")
                return data
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise RuntimeError(f"Model did not return valid JSON for {task}: {last_err}")

    def usage(self) -> dict:
        return {"provider": self.name, "model": self.model, "api_calls": self.calls,
                "cache_hits": self.cached, "tokens_in": self.tokens_in, "tokens_out": self.tokens_out}

    # ----------------------------------------------------------------- private
    def _save(self, task, system, user, text, cached):
        n = len(list(self.raw_dir.glob("*.json"))) + 1
        (self.raw_dir / f"{n:03d}_{task}.json").write_text(json.dumps(
            {"task": task, "provider": self.name, "model": self.model, "from_cache": cached,
             "system": system, "user": user, "response": text}, indent=2, ensure_ascii=False), encoding="utf-8")

    def _wait_turn(self):
        gap = float(self.settings.get("seconds_between_calls", 0))
        wait = self._last_call + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _call(self, system: str, user: str) -> str:
        temperature = float(self.settings.get("temperature", 0.2))
        timeout = float(self.settings.get("timeout_seconds", 180))
        backoff = [10, 30, 60, 120]
        timeouts = 0
        for i in range(len(backoff) + 1):
            self._wait_turn()
            print(f"   waiting for the AI (can take a few minutes; limit {timeout:.0f}s)...", flush=True)
            try:
                if self.kind == "anthropic":
                    r = requests.post(
                        self.cfg.get("base_url", "https://api.anthropic.com") + "/v1/messages",
                        headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                 "content-type": "application/json"},
                        json={"model": self.model, "max_tokens": int(self.settings.get("max_output_tokens", 8000)),
                              "temperature": temperature, "system": system,
                              "messages": [{"role": "user", "content": user}]},
                        timeout=timeout)
                else:
                    body = {"model": self.model, "temperature": temperature,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]}
                    if self.cfg.get("json_mode", True):
                        body["response_format"] = {"type": "json_object"}
                    body.update(self.cfg.get("extra") or {})  # e.g. reasoning_effort: low
                    headers = {"Content-Type": "application/json"}
                    if self.api_key:
                        headers["Authorization"] = f"Bearer {self.api_key}"
                    r = requests.post(self.cfg["base_url"].rstrip("/") + "/chat/completions",
                                      headers=headers, json=body, timeout=timeout)
            except requests.Timeout:
                # A timeout means the model is slow, not broken: retrying the same thing rarely helps.
                timeouts += 1
                if timeouts >= 2:
                    raise RuntimeError(
                        f"The AI took longer than {timeout:.0f}s twice. Fix: raise 'timeout_seconds' in "
                        f"config.yaml, or tell the model to think less (see 'extra' under the provider).")
                print(f"   the AI is slow (no answer in {timeout:.0f}s), trying once more")
                continue
            except requests.RequestException as e:
                if i < len(backoff):
                    print(f"   network problem ({e.__class__.__name__}), retrying in {backoff[i]}s")
                    time.sleep(backoff[i])
                    continue
                raise
            if r.status_code in (429, 500, 502, 503, 504) and i < len(backoff):
                print(f"   service busy / limit hit ({r.status_code}), waiting {backoff[i]}s")
                time.sleep(backoff[i])
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{self.name} error {r.status_code}: {r.text[:500]}")
            data = r.json()
            self.calls += 1
            if self.kind == "anthropic":
                u = data.get("usage", {})
                self.tokens_in += u.get("input_tokens", 0)
                self.tokens_out += u.get("output_tokens", 0)
                return "".join(b.get("text", "") for b in data.get("content", []))
            u = data.get("usage") or {}
            self.tokens_in += u.get("prompt_tokens", 0) or 0
            self.tokens_out += u.get("completion_tokens", 0) or 0
            return data["choices"][0]["message"]["content"] or ""
        raise RuntimeError("Gave up after several retries")
