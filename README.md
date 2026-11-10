# Promo Finder

Reads microdrama screenplays and finds the best **20-60 second promos**: clips that **open on a hook** (something in the first 3 seconds that stops a scroller), **end on a cliffhanger** (an unanswered question), and **make sense to someone who has never seen the show**.

For every promo it gives the episode and the start/end time of every segment (in order), the hook, the cliffhanger, one line on why it works, and a rank.

**On the 50-episode input pack:** 15 AI requests, under 3 minutes, 30 ranked promos (Gemini free tier).

---

## Quick start

You need **Python 3.10 or newer** and a free AI key.

### 1. Get the code and install
```bash
git clone https://github.com/Rahul-chauh212/promo-finder.git
cd promo-finder

python -m venv venv
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# Mac / Linux:
source venv/bin/activate

pip install -r requirements.txt
```

**Windows only:** run this once, then reopen PowerShell. It stops text-format errors with symbols in the scripts:
```
setx PYTHONUTF8 1
```

### 2. Add an AI key
Get a free key from **Google AI Studio** (https://aistudio.google.com → "Get API key", no card needed).
Copy `.env.example` to a new file called `.env` and paste your key:
```
GEMINI_API_KEY=your_key_here
```

### 3. Add the screenplays
Put the episode `.txt` files in the `episodes/` folder. (Kuku's scripts are confidential, so they are not in this repo.)

### 4. Run
```bash
python run.py --provider mock     # practice run: no AI, free, instant (checks your setup)
python run.py --only 1-5          # real AI on episodes 1-5 (quick test)
python run.py                     # real AI on every episode
```

### 5. Read the results
Each run makes a new folder `outputs/run_<date>_<provider>/`:

| File | What it is |
|---|---|
| `report.md` | **Read this first.** Ranked promos, "post these first", details, quality warnings |
| `promos.csv` | The ranked list (opens in Excel / Google Sheets) |
| `review_sheet.csv` | For a human to mark each promo good / ok / bad |
| `promos.json` | Everything, including every hook and cliffhanger found |
| `raw_ai/` | Every question sent to the AI and its unedited answer |

---

## Running it on a NEW show

Put the new show's screenplay files in any folder and point the tool at it:
```bash
python run.py --episodes path/to/new_show
```
Each file needs the same layout as the input pack: an `EPISODE NUMBER: Episode N` line (or the number in the file name, like `episode-007.txt`) and timed lines like:
```
**CHARACTER NAME (Emotion, Emotion):**
Start: (00:39.10) | End: (00:41.20)
"The line of dialogue."
```
`CAMERA`, `ACTION` and `SOUND FX` blocks are read too.

## Web page version
```bash
streamlit run app.py
```
Upload episode files, pick an AI in the sidebar (paste a key or use `.env`), and press **Find promos**. You can download the results as a zip.

## Swapping the AI model

All AI settings live in `config.yaml`. To switch, change `provider:` or pass flags:
```bash
python run.py --provider groq
python run.py --provider gemini --model gemini-3.6-flash
python run.py --provider anthropic        # needs ANTHROPIC_API_KEY in .env
```
Supported: Gemini, Groq, OpenRouter, OpenAI, Anthropic (Claude), local Ollama, and any "OpenAI-compatible" service (add 4 lines to `config.yaml`).

**AI companies retire model names often.** To see which models your key can use right now:
```bash
# Gemini
python -c "import os,requests; from promo_finder.llm import load_env; load_env(); r=requests.get('https://generativelanguage.googleapis.com/v1beta/openai/models', headers={'Authorization':'Bearer '+os.environ['GEMINI_API_KEY']}); print('\n'.join(sorted(m['id'] for m in r.json()['data'])))"
# Groq
python -c "import os,requests; from promo_finder.llm import load_env; load_env(); r=requests.get('https://api.groq.com/openai/v1/models', headers={'Authorization':'Bearer '+os.environ['GROQ_API_KEY']}); print('\n'.join(sorted(m['id'] for m in r.json()['data'])))"
```
Pick a general text model (a "flash" or a large "b" number). Skip anything with `tts`, `image`, `audio`, `whisper` or `guard` in the name.

**Groq tip:** its free tier allows fewer tokens per minute. In `config.yaml`, set `episodes_per_call: 1`, `promos_per_stranger_call: 4` and `seconds_between_calls: 60`.

---

## Troubleshooting

| Error | What it means | Fix |
|---|---|---|
| `404 ... model ... no longer available / does not exist` | That model name was retired | List your models (above) and use `--model <name>`, or change `model:` in `config.yaml` |
| `503 ... experiencing high demand` | The AI company's servers are overloaded (not your code) | The tool retries for about 20 min on its own. Otherwise wait, or try another model or provider |
| `429` | Free daily or per-minute limit reached | Wait (limits reset), or switch provider |
| `400 ... reasoning_effort` | That model doesn't accept the "think less" setting | Delete the `extra:` / `reasoning_effort: low` lines under that provider in `config.yaml` |
| `The AI took longer than ...s twice` | A slow "thinking" model | Raise `timeout_seconds` in `config.yaml`, or keep `reasoning_effort: low` |
| `UnicodeDecodeError` / `charmap` (Windows) | Windows text format | Run `setx PYTHONUTF8 1` and reopen PowerShell |
| `No API key found` | `.env` is missing or misnamed | Make sure the file is called exactly `.env` (not `.env.txt`) and holds `GEMINI_API_KEY=...` |
| `No episode .txt files found` | Wrong folder | Use `--episodes <folder>` |

Nothing is lost when a run fails: finished AI answers are cached in `.cache/`, so re-running continues for free.

---

## How it works (6 steps)

| Step | What happens | Who does it |
|---|---|---|
| 1. Read | Each script is cut into small timed lines with IDs like `E01-027` | Code |
| 2. Find moments | The AI reads 5 episodes at a time and marks hooks (viewer emotion, strength 1-5) and cliffhangers (the open question) | AI, checked by code |
| 3. Build promos | Joins each hook to a later cliffhanger: 20-60 s, hook in the first 3 s, clean cuts (shot ends, never mid-sentence). Can also join the end of one episode to the start of the next | Code |
| 4. Stitch | The AI proposes promos made of 2-3 pieces; code rejects any that are too long or don't open on a hook | AI, checked by code |
| 5. Stranger test | A fresh AI that knows nothing about the show reads only the clip: would I stop? do I understand it? do I need to know what happens next? | AI |
| 6. Rank | Score = hook 30% + cliffhanger 25% + makes sense alone 25% + emotion check 12% + length 8%. Promos sharing more than 50% of their footage count as duplicates | Code |

**The AI must answer with line IDs,** so code can reject made-up lines, hooks after 3 s, and promos outside 20-60 s. Rejected answers are listed in the report.

**The research behind the hooks:** Berger & Milkman (2012) found that high-energy emotions (anger, anxiety, awe) spread more than calm ones (sadness). Loewenstein (1994) describes curiosity as an "information gap", which is what a cliffhanger creates. Code also scores each line's emotion from the script's own tags, e.g. `(Gloating, Smug)`, plus strong words, and flags the promo when this disagrees with the AI.

---

## Checking quality against a human

1. Pick a few episodes and, **before looking at the tool's picks**, write down your own hooks and cliffhangers in `labels/answer_key.csv` (template in `labels/answer_key_TEMPLATE.csv`). For a hook, use the line's **Start** time. For a cliffhanger, use its **End** time:
   ```
   episode,type,time,note
   2,hook,00:00.00,"Gerald says he cannot marry her"
   ```
2. Optionally, mark the top promos `good`, `ok` or `bad` in a run's `review_sheet.csv`.
3. Run:
   ```bash
   python evaluate.py --run outputs/run_XXXX --key labels/answer_key.csv --review outputs/run_XXXX/review_sheet.csv
   ```
   You get `evaluation.md`: how many of your moments the tool found (exactly and within 10 s), how many of its picks match yours, and what it missed.

**Our result (5 episodes, 1 person):** hooks 1/5 exact and 2/5 within 10 s; cliffhangers 0/5 exact and 3/5 within 10 s. The tool usually finds the right scene but not always the right second, and it misses quiet "curiosity" hooks. See the solution doc for the full discussion.

## Tests (no AI, no requests)
```bash
python -m tests.test_with_fake_ai
```
This feeds the pipeline fake AI answers, including deliberately wrong ones (a made-up line ID, a 285 s promo), and checks that the code catches them. It needs episodes 1 and 30 in `episodes/`. It should print a line starting with `OK:`.

## Known limits
- It reads the **script, not the video**, so it can't judge acting, music or how a shot looks.
- Picks can change when you switch AI models.
- It doesn't yet check for spoilers. A late-show twist can rank high.
- Practice mode (`mock`) uses keyword rules only. It is for testing the setup, not for real picks.

## Files
```
run.py                     run from the terminal
app.py                     web page (Streamlit)
evaluate.py                compare against a human answer key
config.yaml                all settings: AI provider, model, rules, weights
promo_finder/parse.py      step 1: read scripts
promo_finder/emotions.py   research-based emotion check (no AI)
promo_finder/prompts.py    every question asked to the AI, in plain English
promo_finder/llm.py        connector for any AI + cache + retries + raw logs
promo_finder/pipeline.py   steps 2-6
promo_finder/report.py     report.md / CSV files
tests/test_with_fake_ai.py checks the code catches bad AI answers
labels/                    answer-key and ad-study templates
```

## References
- Berger, J. & Milkman, K. (2012). *What Makes Online Content Viral?* Journal of Marketing Research.
- Loewenstein, G. (1994). *The Psychology of Curiosity: A Review and Reinterpretation.* Psychological Bulletin.
- Papalampidi, P., Keller, F. & Lapata, M. (2021). *Film Trailer Generation via Task Decomposition.*