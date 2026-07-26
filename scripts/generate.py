#!/usr/bin/env python3
"""StillInLife — daily generator.

Runs once a day. Reads the day's news, asks Claude to distill it into a single
physical object, injects that object into the pronkstilleven prompt, and asks
Nano Banana 2 (via Kie.ai) to paint the next slice of an endless dark banquet
table. Each slice continues seamlessly from the previous one.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import feedparser
import requests
from anthropic import Anthropic
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "prompt_config.json"
MANIFEST_PATH = ROOT / "state" / "manifest.json"
OUTPUT_DIR = ROOT / "output"
TABLE_REL = "reference/Table1.png"

ROME = ZoneInfo("Europe/Rome")
NEWS_RSS = "https://news.google.com/rss?hl=it&gl=IT&ceid=IT:it"
KIE_CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD = "https://api.kie.ai/api/v1/jobs/recordInfo"
KIE_MODEL = "nano-banana-2"
CLAUDE_MODEL = "claude-opus-4-8"
HISTORY_FOR_CLAUDE = 30  # how many past objects to show Claude to avoid repeats


# --------------------------------------------------------------------------- #
# Structured output from Claude
# --------------------------------------------------------------------------- #
class DailyObject(BaseModel):
    object: str          # short English noun phrase, e.g. "a cracked smartphone"
    render_desc: str     # English, in the 17th-c oil style, decontextualized
    symbolism: str       # short Italian note on the link to the news
    headline_ref: str    # the Italian headline it was drawn from


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_manifest() -> list[dict]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return []


def raw_url(rel_path: str) -> str:
    """Public raw.githubusercontent URL for a repo-relative path on main."""
    repo = os.environ["GITHUB_REPOSITORY"]  # e.g. "roberto/StillInLife"
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel_path}"


def fetch_headlines(limit: int = 10) -> list[str]:
    feed = feedparser.parse(NEWS_RSS)
    titles = [e.title.strip() for e in feed.entries if getattr(e, "title", "").strip()]
    if not titles:
        raise RuntimeError("No headlines fetched from Google News RSS.")
    return titles[:limit]


def extract_object(headlines: list[str], past_objects: list[str]) -> DailyObject:
    client = Anthropic()  # reads ANTHROPIC_API_KEY
    avoid = "\n".join(f"- {o}" for o in past_objects[-HISTORY_FOR_CLAUDE:]) or "(none yet)"
    news = "\n".join(f"- {h}" for h in headlines)

    prompt = f"""You curate an art project: an endless 17th-century Dutch banquet
still life (pronkstilleven) painted in near-total darkness. Each day ONE extra
object is added to the table — an object distilled from that day's news, but
decontextualized and anachronistic, out of place among the antique clutter.

Today's Italian headlines:
{news}

Pick a SINGLE physical, paintable object that captures the day — either a
concrete object literally present in the news, or an abstract theme rendered as
a tangible object (e.g. inflation -> a worn, clipped coin). Rules:
- exactly one object, physically renderable in oil paint
- no real logos, faces, brand names, or text
- it should feel anachronistic / surreal against a Baroque table
- do NOT repeat any of these already-used objects:
{avoid}

Return the object as a short English noun phrase, a rich English render
description in the same tenebrist oil style, a short Italian note on how it
links to the news, and the Italian headline it came from."""

    resp = client.messages.parse(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
        output_format=DailyObject,
    )
    result = resp.parsed_output
    if result is None:
        raise RuntimeError("Claude returned no parseable object.")
    return result


def build_prompt(daily: Optional[DailyObject], has_prev: bool) -> str:
    """A single 16:9 slice of one endless table.

    daily=None  → a plain 'filler' slice (fresh clutter, no news object).
    daily=obj   → the day's object slice.
    has_prev    → this slice continues the previous slice on its left edge.
    """
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    parts = [json.dumps(config, ensure_ascii=False, indent=2)]

    if has_prev:
        parts.append(
            "CONTINUITY — the FIRST attached image is the previous slice of this "
            "endless table. Continue the table seamlessly to the RIGHT of it: the "
            "wood, tone, table height, front edge and near-total darkness must "
            "match and align exactly at the left edge, so the two images sit side "
            "by side as one unbroken continuous table. Objects near the seam may "
            "continue across it. The LAST attached image is the fixed reference "
            "table for style and colour — never change the table itself."
        )
    else:
        parts.append(
            "This is the START of an endless 16:9 table. The attached image is the "
            "fixed reference table — keep it exactly as shown (wood, colour, front "
            "edge, height, perspective, near-total darkness). Everything ON it changes."
        )

    if daily is not None:
        parts.append(
            "DAILY OBJECT — among the antique clutter include exactly ONE extra "
            f"object: {daily.render_desc} Painted in the same 17th-century Dutch "
            "oil realism and near-total darkness, decontextualized and "
            "anachronistic, resting naturally on the table among the antique objects."
        )

    return "\n\n".join(parts)


def kie_generate(prompt: str, image_urls: list[str], api_key: str) -> str:
    """Create a task, poll until success, return the result image URL."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": KIE_MODEL,
        "input": {
            "prompt": prompt,
            "image_input": image_urls,
            "aspect_ratio": "16:9",
            "resolution": "2K",
            "output_format": "png",
        },
    }
    r = requests.post(KIE_CREATE, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"Kie createTask failed: {payload}")
    task_id = payload["data"]["taskId"]
    print(f"Kie task created: {task_id}")

    deadline = time.time() + 900  # 15 min
    while time.time() < deadline:
        time.sleep(10)
        q = requests.get(KIE_RECORD, headers=headers, params={"taskId": task_id}, timeout=60)
        q.raise_for_status()
        data = q.json().get("data", {})
        state = data.get("state")
        print(f"  state={state} progress={data.get('progress')}")
        if state == "success":
            result_json = json.loads(data["resultJson"])
            urls = result_json.get("resultUrls") or result_json.get("result_urls")
            if not urls:
                raise RuntimeError(f"No resultUrls in: {result_json}")
            return urls[0]
        if state == "fail":
            raise RuntimeError(f"Kie task failed: {data.get('failMsg')}")
    raise RuntimeError("Kie task timed out after 15 minutes.")


def download(url: str, dest: Path) -> None:
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    now_rome = datetime.now(ROME)
    if os.environ.get("FORCE_RUN") != "1" and now_rome.hour != 9:
        print(f"Not 09:00 in Rome (now {now_rome:%H:%M}); skipping. Set FORCE_RUN=1 to override.")
        return 0

    kie_key = os.environ.get("KIE_API_KEY")
    if not kie_key:
        print("KIE_API_KEY is not set.", file=sys.stderr)
        return 1

    date_str = now_rome.strftime("%Y-%m-%d")
    normal_rel = f"output/{date_str}-a.png"   # filler table slice (no news object)
    object_rel = f"output/{date_str}-b.png"   # slice carrying the day's object
    if (ROOT / object_rel).exists():
        print(f"{object_rel} already exists; nothing to do.")
        return 0

    manifest = load_manifest()
    past_objects = [e["object"] for e in manifest if e.get("object")]

    print("Fetching headlines…")
    headlines = fetch_headlines()

    print("Asking Claude for today's object…")
    daily = extract_object(headlines, past_objects)
    print(f"Object: {daily.object}\nSymbolism: {daily.symbolism}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    table_url = raw_url(TABLE_REL)

    # 1) Normal slice — continues yesterday's last committed slice (or the table
    #    itself on day one). It has no news object, only fresh random clutter.
    prev_ref = raw_url(manifest[-1]["file"]) if manifest else None
    normal_refs = [prev_ref, table_url] if prev_ref else [table_url]
    print("Generating the plain filler slice…")
    normal_url = kie_generate(build_prompt(None, has_prev=bool(prev_ref)), normal_refs, kie_key)
    download(normal_url, ROOT / normal_rel)

    # 2) Object slice — continues the plain slice we just made. We feed Kie the
    #    freshly-returned normal_url directly (already hosted), so we don't need
    #    it committed to GitHub first.
    print("Generating the object slice (continuing the filler)…")
    object_refs = [normal_url, table_url]
    object_url = kie_generate(build_prompt(daily, has_prev=True), object_refs, kie_key)
    download(object_url, ROOT / object_rel)

    manifest.append({
        "date": date_str, "file": normal_rel, "type": "normal",
        "object": "", "symbolism": "", "headline": "",
    })
    manifest.append({
        "date": date_str, "file": object_rel, "type": "object",
        "object": daily.object, "symbolism": daily.symbolism, "headline": daily.headline_ref,
    })
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved 2 slices; manifest now has {len(manifest)} slices.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
