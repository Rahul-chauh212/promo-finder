"""All the questions we ask the AI, in one place, written in plain English.

Each question asks for a fixed "form" (JSON) so code can check and score it.
The AI must point at line IDs from the script, never invent text.
"""

SYSTEM = """You are a senior promo editor for vertical micro-drama apps (like ReelShort and DramaBox).
You pick 20-60 second clips from a show that make a stranger scrolling TikTok/Instagram stop, watch, and need to know what happens next.

What works, based on research:
- Hooks that cause HIGH-ENERGY emotions stop the scroll: anger/outrage at injustice, shock at a reveal,
  fear/threat, triumph (a power reversal, revenge, a hidden identity revealed), desire.
  Calm emotions (plain sadness, tenderness) are weak hooks, even if the scene is important.
- A physical action (a slap, a grab, someone kneeling, a ring thrown) or a single shocking line is the best hook.
- Cliffhangers work by leaving ONE clear, specific question open ("Will she be hanged?", "Who is the real father?").
  A cut is NOT a cliffhanger if the answer comes in the next line.
- A stranger must understand who is hurting whom from the clip itself. Inside jokes, names with no
  context, or plot that needs earlier episodes make a promo fail.

Rules: only use line IDs that appear in the input. Never invent dialogue. Reply with one JSON object only."""


def moment_finder(story_so_far: str, episodes_text: str, n_hooks: int, n_cliffs: int,
                  emotions: list[str]) -> str:
    return f"""STORY SO FAR (one line per earlier episode, for your context only):
{story_so_far or "(this is the start of the show)"}

Below are full episodes. Each line is: ID [start-end] SPEAKER (script emotion tags): text

{episodes_text}

TASK - for EACH episode above, find:
1. Up to {n_hooks} HOOKS: moments that would stop a scroller in the first 3 seconds of a promo.
   - "hook_line_id": the line where the hook lands (the slap / the shocking line / the reveal).
   - "start_line_id": where the clip should begin. Usually the same as hook_line_id, or the line just
     before it if one quick setup line makes the hook land harder. It must start at most 3 seconds before the hook.
   - "viewer_emotion": one of {emotions} (what a VIEWER feels, not the character).
   - "strength": 1-5 (5 = almost anyone would stop; 3 = decent; 1 = weak).
   - "why": a few words.
2. Up to {n_cliffs} CLIFFHANGERS: lines where cutting RIGHT AFTER leaves a burning open question.
   - "line_id", "open_question" (the question the viewer is left with), "strength": 1-5.
   - Do not pick a line whose question is answered in the next line or two.
   - The last line of an episode is NOT automatically a cliffhanger. A resolution (a happy ending, a couple
     walking away together, a fade-out after the problem is solved) is not a cliffhanger.
   - For hooks, do not pick a line that starts with "..." (the middle of a sentence); pick where the sentence starts.

Spread picks across the episode; do not pick the same moment twice.

Reply with JSON exactly like:
{{"episodes": [
  {{"episode": 1,
    "hooks": [{{"start_line_id": "E01-008", "hook_line_id": "E01-008", "viewer_emotion": "shock", "strength": 4, "why": "..."}}],
    "cliffhangers": [{{"line_id": "E01-040", "open_question": "...", "strength": 5}}]
  }}
]}}"""


def stitcher(story: str, hooks_text: str, cliffs_text: str, n: int, min_s: int, max_s: int) -> str:
    return f"""SHOW SUMMARY (one line per episode):
{story}

STRONGEST HOOK MOMENTS FOUND (ID | episode time | what happens):
{hooks_text}

STRONGEST CLIFFHANGER MOMENTS FOUND:
{cliffs_text}

TASK - propose up to {n} STITCHED promos. A stitched promo joins 2 or 3 short pieces (from one episode
or across episodes) into one {min_s}-{max_s} second clip that tells a mini-story a stranger understands:
open on a hook -> one piece of context or escalation -> end on a cliffhanger.
Typical shape: "betrayal" -> "she swears revenge / power flip" -> "the moment before the answer".

Each piece is given as start_line_id and end_line_id (inclusive, same episode, in time order inside the piece).
The first piece must START on a hook moment. The last piece must END on a cliffhanger moment.
Keep each piece short (about 5-20 seconds). Avoid spoiling the show's biggest final twist.

Reply with JSON exactly like:
{{"promos": [
  {{"title": "short name",
    "segments": [{{"start_line_id": "E01-030", "end_line_id": "E01-034"}}, {{"start_line_id": "E05-010", "end_line_id": "E05-016"}}],
    "hook": "what the first 3 seconds show",
    "cliffhanger": "the open question at the end",
    "why": "one line on why it works"}}
]}}"""


STRANGER_SYSTEM = """You are an ordinary person scrolling TikTok. You have NEVER seen this show and know nothing about it.
You will read the script of short video clips (what is seen and heard, in order). Judge each clip only from what is in it.
Be honest and strict: if you would not understand who is who, say so. Reply with one JSON object only."""


def stranger_test(clips_text: str) -> str:
    return f"""Here are several clips. Each one is what a viewer would see and hear, in order.

{clips_text}

For EACH clip, answer:
- "id": the clip id
- "what_happens": one sentence in your own words
- "first_3_seconds": what grabs (or fails to grab) you in the first 3 seconds
- "grab": 1-5, would you stop scrolling in the first 3 seconds?
- "makes_sense_alone": 1-5, do you understand what is going on without having seen the show?
- "need_to_know_next": 1-5, how badly do you want to see what happens next?
- "open_question": the question you are left with (or "none")
- "confusing": anything confusing (or "nothing")
- "why_it_works": one short line an editor could use (or why it does not work)

Reply with JSON exactly like:
{{"clips": [{{"id": "P01", "what_happens": "...", "first_3_seconds": "...", "grab": 4, "makes_sense_alone": 5,
  "need_to_know_next": 4, "open_question": "...", "confusing": "nothing", "why_it_works": "..."}}]}}"""
