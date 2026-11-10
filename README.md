# Promo Finder

Reads microdrama screenplays and finds the best **20-60 second promos**: clips that **open on a hook** (something in the first 3 seconds that stops a scroller), **end on a cliffhanger** (an unanswered question), and **make sense to a stranger**. For each promo it gives the episode and start/end time of every segment, the hook, the cliffhanger, one line on why it works, and a rank.

---

## How it works (6 steps)

| Step | What happens | Who does it |
|---|---|---|
| 1. Read | Each script is cut into small timed lines with IDs like `E01-027` | Code |
| 2. Find moments | The AI reads 5 episodes at a time and marks hooks (with the viewer emotion, strength 1-5) and cliffhangers (with the open question) | AI, checked by code |
| 3. Build promos | Code joins each hook to a later cliffhanger: 20-60 s long, hook inside the first 3 s, cuts at clean points (shot ends, never mid-sentence). Also joins the end of one episode to the start of the next | Code |
| 4. Stitch | The AI proposes promos made of 2-3 pieces (e.g. betrayal in Ep 1 + "she will hang" in Ep 30). Code rejects any that are too long or don't open on a hook | AI, checked by code |
| 5. Stranger test | A *fresh* AI that knows nothing about the show reads only the clip and answers: would I stop? do I understand it? do I need to know what happens next? | AI |
| 6. Rank | Score = hook + cliffhanger + makes sense alone + emotion check + good length. Duplicates (more than 50% shared footage) are removed | Code |

**Code double-checks everything the AI says.** The AI must answer with line IDs, so code can reject any made-up line, any hook that lands after 3 s, and any promo outside 20-60 s. Rejected answers are listed in the report.

**The emotion check is based on research.** Berger & Milkman (2012) found that high-energy emotions (anger, anxiety, awe) spread more and calm ones (sadness) spread less. Loewenstein (1994) explains curiosity as an "information gap", which is what a cliffhanger creates. The tool reads the emotion tags already written in the script, e.g. `(Gloating, Smug)`, plus strong words ("poison", "hang", "betray"). If the AI calls a moment "anger" but the script looks calm, the promo is flagged.

---

## Setup (once, about 5 minutes)

1. Install Python 3.10 or newer.
2. In this folder, run:
   ```
   pip install -r requirements.txt
   ```
3. Get a free AI key. Easiest: **Google AI Studio** (https://aistudio.google.com) → "Get API key" (no card needed).
   Copy `.env.example` to `.env` and paste the key: `GEMINI_API_KEY=your_key_here`.
4. Copy the 50 episode `.txt` files into the `episodes/` folder.

## Run it

```
python run.py --provider mock          # practice run, no AI, free and instant
python run.py --only 1-5               # real AI on episodes 1-5 (quick test)
python run.py                          # real AI on everything
streamlit run app.py                   # the web page version
```

Each run creates `outputs/run_<date>_<provider>/` containing:
- `report.md`: **read this first.** Ranked promos, "post these first", details, and the quality check
- `promos.csv`: the ranked list (opens in Excel or Google Sheets)
- `review_sheet.csv`: for you to mark each promo good/ok/bad
- `promos.json`: everything, including all hooks and cliffhangers found
- `raw_ai/`: every question sent to the AI and its unedited answer (the brief asks for raw outputs)

**Swapping the AI** = change `provider:` in `config.yaml`, or use `--provider groq --model <name>`. Supported: Gemini, Groq, OpenRouter, OpenAI, Anthropic (Claude), local Ollama, and any other "OpenAI-compatible" service (add 4 lines to `config.yaml`).

**Requests and cost.** 50 episodes take about **15 AI requests** (10 for moments, 1 for stitching, 3-4 for the stranger test), roughly 150-250k tokens in total. That fits a free tier. Answers are cached, so re-running costs nothing. Free tiers change often; if you hit a limit, the tool waits and retries, or you can run in parts with `--only`.

---

## Your part (the human in the loop)

The tool can't prove it is right on its own. These steps give it something to be measured against.

**A. Make the answer key (about 40 minutes). Do this BEFORE looking at the tool's picks.**
1. Pick 8 episodes spread across the show, for example 1, 2, 8, 15, 23, 30, 41, 50.
2. Read each script and choose 1-3 **hooks** (moments that would make you stop scrolling) and 1-2 **cliffhangers** (points where cutting would leave you desperate to know more).
3. Write them in `labels/answer_key.csv` (copy `answer_key_TEMPLATE.csv`):
   ```
   episode,type,time,note
   1,hook,00:39,"sister: Because he is marrying me"
   1,cliffhanger,02:17,"face hardens, cut to black"
   ```
   For a hook, use the line's **Start** time. For a cliffhanger, use the line's **End** time.

**B. Review the tool's top 15 (about 15 minutes).** Open `review_sheet.csv` from a run and fill `your_verdict` with `good`, `ok` or `bad`, plus a short note on bad ones.

**C. Then run:**
```
python evaluate.py --run outputs/run_xxx --key labels/answer_key.csv --review outputs/run_xxx/review_sheet.csv
```
This writes `evaluation.md` with: how many of your moments the tool found, how many of its picks match yours, what it missed, and how many of the top 10 you rated good. These numbers go in your solution doc under "how you know it's good".

**D. Optional but strong: study 10 real ads.** Watch 10 ReelShort/DramaBox promos and fill `labels/real_promo_study_TEMPLATE.csv` (what's in the first 3 seconds, which emotion, how it ends). This checks whether the research (which studied *sharing articles*) really holds for *drama ads*.

---

## Where it can go wrong (known limits)

- It reads the **script, not the video**: it can't see acting quality, music, or whether a shot actually looks good.
- **Stand-alone sense** is judged by an AI pretending to be a stranger. It may be more (or less) forgiving than a real person.
- AI scores can be overconfident. Research shows LLMs name emotions well but don't show when humans would *disagree*. That's why there's an emotion cross-check and a human answer key.
- Cross-episode promos assume the next episode does not start with a recap; check them before posting.
- Practice mode (`mock`) only uses keyword rules. It is for testing the pipeline, not for real picks.

## Files

```
run.py                  run from terminal
app.py                  web page (Streamlit)
evaluate.py             compare against your answer key
config.yaml             all settings: AI provider, rules, weights
promo_finder/parse.py     step 1: read scripts
promo_finder/emotions.py  research-based emotion check (no AI)
promo_finder/prompts.py   every question asked to the AI, in plain English
promo_finder/llm.py       connector for any AI + cache + raw logs
promo_finder/pipeline.py  steps 2-6
promo_finder/report.py    report.md / CSV files
tests/test_with_fake_ai.py  checks the code catches bad AI answers
```

## References
- Berger, J. & Milkman, K. (2012). *What Makes Online Content Viral?* Journal of Marketing Research.
- Loewenstein, G. (1994). *The Psychology of Curiosity: A Review and Reinterpretation.* Psychological Bulletin.
- Papalampidi, Keller & Lapata (2021). *Film Trailer Generation via Task Decomposition* (splits trailers into story turning points + emotion, the same idea used here).
