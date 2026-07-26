#!/usr/bin/env python3
"""StillInLife — daily generator.

Every day at 09:00 Rome the project extends one endless dark banquet table by two
stitched slices:

  … filler(yesterday) · [9AM object band] · filler(today) · [9AM object band] …

- The OBJECT band is a narrow 9:16 portion of the table carrying the day's object
  (distilled from the news).
- The FILLER is a wide 16:9 stretch of fresh antique clutter that fills the time
  until the next 9AM.

Continuity is pushed as far as Nano Banana 2 allows: each new slice is generated
from the right-edge crop of the previous slice, instructed to resume exactly where
it ends. The viewer scrolls the strip left, time-synchronised, so each 9AM object
reaches the "now" line at exactly 09:00.
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
from PIL import Image
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
CLAUDE_MODEL = "claude-haiku-4-5"
HISTORY_FOR_CLAUDE = 30

OBJ_ASPECT = "9:16"    # narrow object band — only a portion of the table
FILL_ASPECT = "16:9"   # wide filler stretch
RESOLUTION = "2K"
EDGE_FRAC = 0.22       # fraction of width kept as the seam reference for tomorrow


class DailyObject(BaseModel):
    object: str
    render_desc: str
    symbolism: str
    headline_ref: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_manifest() -> list[dict]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return []


def raw_url(rel_path: str) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel_path}"


def last_edge_rel(manifest: list[dict]) -> Optional[str]:
    """Right-edge crop of the most recent filler — the seam for today's object."""
    for entry in reversed(manifest):
        if entry.get("edge"):
            return entry["edge"]
    return None


def fetch_headlines(limit: int = 10) -> list[str]:
    feed = feedparser.parse(NEWS_RSS)
    titles = [e.title.strip() for e in feed.entries if getattr(e, "title", "").strip()]
    if not titles:
        raise RuntimeError("No headlines fetched from Google News RSS.")
    return titles[:limit]


def extract_object(headlines: list[str], past_objects: list[str]) -> DailyObject:
    client = Anthropic()
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
        messages=[{"role": "user", "content": prompt}],
        output_format=DailyObject,
    )
    if resp.parsed_output is None:
        raise RuntimeError("Claude returned no parseable object.")
    return resp.parsed_output


def build_prompt(daily: Optional[DailyObject], kind: str, has_prev: bool) -> str:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    parts = [json.dumps(config, ensure_ascii=False, indent=2)]

    if has_prev:
        parts.append(
            "SEAM — the attached image is the EXACT RIGHT EDGE of the endless table "
            "so far. Your image must begin EXACTLY where that edge ends: the "
            "leftmost column continues it seamlessly — identical wood, identical "
            "table height and front edge, identical near-total darkness, and any "
            "object touching the seam carries straight across it. Do NOT restart or "
            "recompose the scene; you are only extending the same table to the right."
        )
    else:
        parts.append(
            "This is the START of an endless table. The attached image is the fixed "
            "reference table — keep it exactly (wood, colour, front edge, height, "
            "perspective, near-total darkness). Everything ON it changes."
        )

    if kind == "object":
        obj = daily.render_desc if daily else ""
        parts.append(
            "FORMAT — a NARROW vertical 9:16 band: only a small portion of the "
            "table, not a full scene. Among a little antique clutter feature exactly "
            f"ONE object: {obj} Painted in the same 17th-century Dutch oil realism "
            "and near-total darkness, decontextualized and anachronistic."
        )
    else:  # filler
        parts.append(
            "FORMAT — a WIDE 16:9 stretch of the same table, filled with fresh "
            "antique clutter (draw from the pools). NO extra news object here — just "
            "the maximalist dark still life continuing the table."
        )
    return "\n\n".join(parts)


def kie_generate(prompt: str, image_urls: list[str], aspect: str, api_key: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": KIE_MODEL,
        "input": {
            "prompt": prompt,
            "image_input": image_urls,
            "aspect_ratio": aspect,
            "resolution": RESOLUTION,
            "output_format": "png",
        },
    }
    r = requests.post(KIE_CREATE, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"Kie createTask failed: {payload}")
    task_id = payload["data"]["taskId"]
    print(f"  Kie task {task_id} ({aspect})")
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(10)
        q = requests.get(KIE_RECORD, headers=headers, params={"taskId": task_id}, timeout=60)
        q.raise_for_status()
        data = q.json().get("data", {})
        state = data.get("state")
        print(f"    state={state} progress={data.get('progress')}")
        if state == "success":
            result = json.loads(data["resultJson"])
            urls = result.get("resultUrls") or result.get("result_urls")
            if not urls:
                raise RuntimeError(f"No resultUrls in: {result}")
            return urls[0]
        if state == "fail":
            raise RuntimeError(f"Kie task failed: {data.get('failMsg')}")
    raise RuntimeError("Kie task timed out after 15 minutes.")


def download(url: str, dest: Path) -> None:
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)


def crop_right_edge(src: Path, dst: Path, frac: float = EDGE_FRAC) -> None:
    """Save the rightmost `frac` of the image — the seam reference for tomorrow."""
    with Image.open(src) as im:
        w, h = im.size
        band = max(1, int(w * frac))
        im.crop((w - band, 0, w, h)).save(dst)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    now_rome = datetime.now(ROME)
    if os.environ.get("FORCE_RUN") != "1" and now_rome.hour != 9:
        print(f"Not 09:00 in Rome (now {now_rome:%H:%M}); skipping. Set FORCE_RUN=1.")
        return 0

    kie_key = os.environ.get("KIE_API_KEY")
    if not kie_key:
        print("KIE_API_KEY is not set.", file=sys.stderr)
        return 1

    date_str = now_rome.strftime("%Y-%m-%d")
    obj_rel = f"output/{date_str}-obj.png"
    fill_rel = f"output/{date_str}-fill.png"
    edge_rel = f"output/{date_str}-edge.png"
    if (ROOT / obj_rel).exists():
        print(f"{obj_rel} already exists; nothing to do.")
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

    # 1) OBJECT band — continues yesterday's filler edge (or the table on day one).
    prev_edge = last_edge_rel(manifest)
    obj_refs = [raw_url(prev_edge)] if prev_edge else [table_url]
    print("Generating the 9AM object band…")
    obj_url = kie_generate(
        build_prompt(daily, kind="object", has_prev=bool(prev_edge)),
        obj_refs, OBJ_ASPECT, kie_key,
    )
    download(obj_url, ROOT / obj_rel)

    # 2) FILLER — continues today's object band (use its live Kie URL directly).
    print("Generating the filler stretch…")
    fill_url = kie_generate(
        build_prompt(None, kind="filler", has_prev=True),
        [obj_url], FILL_ASPECT, kie_key,
    )
    download(fill_url, ROOT / fill_rel)

    # 3) Right-edge crop of the filler = tomorrow's seam.
    crop_right_edge(ROOT / fill_rel, ROOT / edge_rel)

    anchor_iso = now_rome.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
    seq = len(manifest)
    manifest.append({
        "seq": seq, "date": date_str, "file": obj_rel, "type": "object",
        "anchor": anchor_iso,  # this band reaches the 'now' line at 09:00 today
        "object": daily.object, "symbolism": daily.symbolism, "headline": daily.headline_ref,
    })
    manifest.append({
        "seq": seq + 1, "date": date_str, "file": fill_rel, "type": "filler",
        "edge": edge_rel, "object": "", "symbolism": "", "headline": "",
    })
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved object + filler; manifest now has {len(manifest)} slices.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
