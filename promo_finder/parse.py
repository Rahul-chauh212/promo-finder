"""Step 1 - Read a screenplay file and cut it into small timed pieces ("lines").

No AI here. Plain rules only, so this part is fast, free and always the same.

Every line gets an ID like E01-023 (episode 1, line 23). The AI is asked to
answer with these IDs, so code can check that every answer points at a real
line with a real timestamp (no made-up moments).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

TIME_RE = re.compile(r"Start:\s*\((\d+:\d+(?:\.\d+)?)\)\s*\|\s*End:\s*\((\d+:\d+(?:\.\d+)?)\)")
HEADER_RE = re.compile(r"^\*\*(.+?):\*\*\s*$")
PAREN_RE = re.compile(r"\(([^()]*)\)")

# Headers that are not a person speaking.
NON_SPEECH = {
    "CAMERA": "camera", "ACTION": "action", "SOUND FX": "sound", "SFX": "sound",
    "SOUND": "sound", "MUSIC": "sound", "VFX": "action", "TRANSITION": "camera",
    "INSERT": "camera", "TEXT ON SCREEN": "action", "SUPER": "action",
}
NOT_TAGS = {"O.S.", "V.O.", "CONT'D", "O.C.", "OS", "VO"}


def to_sec(s: str) -> float:
    m, sec = s.split(":")
    return int(m) * 60 + float(sec)


def fmt(t: float) -> str:
    """Seconds -> 'MM:SS.ss' (same style as the scripts)."""
    t = max(0.0, t)
    m = int(t // 60)
    return f"{m:02d}:{t - 60 * m:05.2f}"


@dataclass
class Line:
    id: str
    episode: int
    scene: int
    kind: str            # dialogue | action | camera | sound
    speaker: str | None
    tags: list[str]      # emotion tags written in the script, e.g. ["Gloating", "Smug"]
    start: float
    end: float
    text: str

    def short(self) -> str:
        """One compact line for the AI to read."""
        who = ""
        if self.kind == "dialogue":
            who = f"{self.speaker}" + (f" ({', '.join(self.tags)})" if self.tags else "") + ": "
        elif self.kind != "camera":
            who = f"[{self.kind.upper()}] "
        else:
            who = "[SHOT] "
        return f"{self.id} [{fmt(self.start)}-{fmt(self.end)}] {who}{self.text}"


@dataclass
class Episode:
    number: int
    logline: str
    continuity: str
    duration: float
    lines: list[Line] = field(default_factory=list)
    file: str = ""

    def line(self, line_id: str) -> Line | None:
        for ln in self.lines:
            if ln.id == line_id:
                return ln
        return None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _split_header(head: str) -> tuple[str, str | None, list[str]]:
    """'LADY IN GOLD GOWN (Gloating, Smug)' -> ('dialogue', 'LADY IN GOLD GOWN', ['Gloating','Smug'])"""
    up = head.strip().upper()
    if up in NON_SPEECH:
        return NON_SPEECH[up], None, []
    groups = PAREN_RE.findall(head)
    speaker = head.split("(")[0].strip()
    extra = [g.strip() for g in groups if g.strip().upper() in NOT_TAGS]
    if extra:
        speaker += " (" + ", ".join(extra) + ")"
    tags: list[str] = []
    for g in groups:
        if g.strip().upper() in NOT_TAGS:
            continue
        tags += [t.strip() for t in g.split(",") if t.strip()]
    return "dialogue", speaker, tags


def parse_episode(path: str | Path) -> Episode:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    rows = raw.split("\n")

    number = None
    m = re.search(r"EPISODE NUMBER:\s*Episode\s*(\d+)", raw, re.I)
    if m:
        number = int(m.group(1))
    else:
        m = re.search(r"episode[-_ ]?0*(\d+)", path.name, re.I)
        number = int(m.group(1)) if m else 0

    def field_value(name: str) -> str:
        mm = re.search(rf"^{name}:\s*(.*)$", raw, re.I | re.M)
        return mm.group(1).strip() if mm else ""

    ep = Episode(number=number, logline=field_value("EPISODE LOGLINE"),
                 continuity=field_value("CONTINUITY NOTES"), duration=0.0, file=path.name)

    scene = 0
    i = 0
    count = 0
    while i < len(rows):
        row = rows[i].strip()
        sm = re.match(r"^SCENE\s+(\d+)", row)
        if sm:
            scene = int(sm.group(1))
            i += 1
            continue
        hm = HEADER_RE.match(row)
        if hm:
            head = hm.group(1)
            # next non-empty row should hold Start/End
            j = i + 1
            while j < len(rows) and not rows[j].strip():
                j += 1
            tm = TIME_RE.search(rows[j]) if j < len(rows) else None
            if not tm:
                i += 1
                continue
            start, end = to_sec(tm.group(1)), to_sec(tm.group(2))
            # text = following rows until blank row or next header
            k = j + 1
            text_rows = []
            while k < len(rows) and rows[k].strip() and not HEADER_RE.match(rows[k].strip()):
                text_rows.append(rows[k].strip())
                k += 1
            text = " ".join(text_rows).strip()
            kind, speaker, tags = _split_header(head)
            # Safety net: quoted text is speech even if the header looks odd.
            if kind != "dialogue" and text.startswith('"') and head.strip().upper() not in NON_SPEECH:
                kind = "dialogue"
            count += 1
            ep.lines.append(Line(
                id=f"E{number:02d}-{count:03d}", episode=number, scene=scene, kind=kind,
                speaker=speaker, tags=tags, start=start, end=max(end, start), text=text.strip('"'),
            ))
            i = k
            continue
        i += 1

    ep.duration = max((ln.end for ln in ep.lines), default=0.0)
    m = re.search(r"Scene end:\s*(\d+:\d+(?:\.\d+)?)", raw)
    ends = [to_sec(x) for x in re.findall(r"Scene end:\s*(\d+:\d+(?:\.\d+)?)", raw)]
    if ends:
        ep.duration = max(ep.duration, max(ends))
    return ep


def load_folder(folder: str | Path) -> list[Episode]:
    files = sorted(Path(folder).glob("*.txt"))
    eps = [parse_episode(f) for f in files]
    eps = [e for e in eps if e.lines]
    eps.sort(key=lambda e: e.number)
    return eps
