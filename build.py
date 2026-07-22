#!/usr/bin/env python3
"""Build words.master.json from seed.txt.

Seed lines are pipe-delimited: `word | optional inline definition | optional type`.
Lines beginning with # are comments/section headers and are ignored.

For each word we fetch phonetic (IPA) and all sense meanings from the Free
Dictionary API (dictionaryapi.dev). Inline overrides win over the API, which
keeps coined words the API doesn't know (e.g. "sonder").

cache.json stores the *raw* meanings per word, so sense selection and cleanup
can be re-tuned and the master rebuilt instantly, without re-hitting the API.
The API rate-limits bursts (429), so we back off and cache incrementally —
reruns resume from the cache.
"""
import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
SEED = HERE / "seed.txt"
OUT = HERE / "words.master.json"
CACHE = HERE / "cache.json"
EXAMPLES = HERE / "examples.txt"
API = "https://api.dictionaryapi.dev/api/v2/entries/en/"

POS = {
    "noun": "n.", "verb": "v.", "adjective": "adj.", "adverb": "adv.",
    "pronoun": "pron.", "preposition": "prep.", "conjunction": "conj.",
    "interjection": "interj.", "exclamation": "interj.",
}

MAX_DEF = 150     # chars; keep it legible in a 1-bit quadrant
REQ_DELAY = 0.5   # seconds between live API calls

# Derived agent-noun glosses ("One who...") are almost never the sense a learner
# wants — the adjective/verb sense is. Penalise them so a better sense wins.
AGENT_GLOSS = re.compile(
    r"^(one (who|of|that|which|motivated|rejected|possessing|having|characteri[sz]ed)"
    r"|a person who|someone who|that which|a person or thing)\b", re.I)


def clean_def(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\((?:[^)]{0,40})\)\s*", "", text)          # leading (obsolete) etc.
    text = re.sub(r"[;,]\s*(?:compare|see|synonym of|cf\.?)\b.*$", "", text, flags=re.I)
    text = text.strip()
    if len(text) > MAX_DEF:                                     # prefer the first sentence
        first = re.split(r"(?<=[.;])\s+", text, maxsplit=1)[0]
        text = first if 20 < len(first) <= MAX_DEF else text
    text = text.rstrip(".").strip()
    if len(text) > MAX_DEF:
        text = text[:MAX_DEF].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if text:
        text = text[0].upper() + text[1:]
    return text


def score(cand: dict, word: str) -> float:
    d = cand["def"]
    s = 0.0
    if AGENT_GLOSS.match(d):
        s -= 100
    if re.search(r"\b" + re.escape(word) + r"\w*\b", d, re.I):  # circular definition
        s -= 40
    if re.search(r"\b(obsolete|archaic|dated|rare)\b", d, re.I):
        s -= 30
    s -= 0.01 * len(d)                                          # gentle nudge to concise
    return s


def select_best(meanings: list, word: str):
    if not meanings:
        return None
    best = max(range(len(meanings)),
               key=lambda i: (score(meanings[i], word), -i))
    return meanings[best]


def api_lookup(word: str) -> dict:
    """Return raw {phonetic, meanings:[{pos,def,example}]} or {"miss":True}."""
    url = API + urllib.parse.quote(word)
    delay = 5
    for _ in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "trmnl-vocab"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"miss": True}
            if e.code in (429, 500, 502, 503, 504):
                ra = e.headers.get("Retry-After", "")
                wait = int(ra) if ra.isdigit() else delay
                print(f"  … {e.code} on {word}, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                delay = min(delay * 2, 60)
                continue
            raise
        except Exception as e:
            print(f"  … error on {word} ({e}), waiting {delay}s", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 60)
    else:
        raise RuntimeError(f"gave up on {word} after retries (rerun to resume from cache)")

    if not isinstance(data, list) or not data:
        return {"miss": True}
    entry = data[0]
    phonetic = entry.get("phonetic") or ""
    if not phonetic:
        for p in entry.get("phonetics", []):
            if p.get("text"):
                phonetic = p["text"]
                break
    meanings = []
    for m in entry.get("meanings", []):
        pos = m.get("partOfSpeech", "")
        for d in (m.get("definitions") or []):
            if d.get("definition", "").strip():
                meanings.append({"pos": pos, "def": d["definition"].strip(),
                                 "example": (d.get("example") or "").strip()})
                break  # first definition per part of speech is enough
    return {"phonetic": phonetic, "meanings": meanings}


def parse_seed():
    seen = set()
    for raw in SEED.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        key = parts[0].lower()
        if key in seen:
            continue
        seen.add(key)
        yield (parts[0],
               parts[1] if len(parts) > 1 and parts[1] else None,
               parts[2] if len(parts) > 2 and parts[2] else None)


def parse_examples():
    """Read examples.txt: `word | example | optional def | optional type`.

    The example is always applied; a definition and type override the
    API/seed value when present (used to fix a handful of wrong-sense entries).
    """
    ex = {}
    if not EXAMPLES.exists():
        return ex
    for raw in EXAMPLES.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[1]:
            continue
        entry = {"example": parts[1]}
        if len(parts) > 2 and parts[2]:
            entry["definition"] = parts[2]
        if len(parts) > 3 and parts[3]:
            entry["type"] = parts[3]
        ex[parts[0].lower()] = entry
    return ex


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    seed = list(parse_seed())
    examples = parse_examples()
    print(f"Seed: {len(seed)} words | cache: {len(cache)} | examples: {len(examples)}",
          file=sys.stderr)

    words, misses, new = [], [], 0
    try:
        for i, (word, inline_def, inline_type) in enumerate(seed, 1):
            key = word.lower()
            if key not in cache:
                cache[key] = api_lookup(word)
                new += 1
                time.sleep(REQ_DELAY)
                if new % 25 == 0:
                    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                    print(f"  ...{i}/{len(seed)} ({new} fetched)", file=sys.stderr)
            raw = cache[key]

            phonetic = "" if raw.get("miss") else raw.get("phonetic", "")
            if inline_def:
                definition, pos, example = clean_def(inline_def), inline_type or "", ""
            else:
                cands = [] if raw.get("miss") else raw.get("meanings", [])
                best = select_best(cands, word)
                if not best:
                    misses.append(word)
                    continue
                definition = clean_def(best["def"])
                pos = POS.get(best["pos"], best["pos"])
                example = best.get("example", "")

            # examples.txt overrides: example always; definition/type when given
            ex = examples.get(key)
            if ex:
                example = ex["example"]
                if ex.get("definition"):
                    definition = clean_def(ex["definition"])
                if ex.get("type"):
                    pos = ex["type"]

            if not definition:
                misses.append(word)
                continue
            entry = {"word": word, "type": pos, "definition": definition}
            if phonetic:
                entry["phonetic"] = phonetic
            if example and len(example) <= 120:
                entry["example"] = example
            words.append(entry)
    finally:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    words.sort(key=lambda w: w["word"].lower())
    OUT.write_text(json.dumps({"words": words}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"\nWrote {len(words)} words to {OUT.name}", file=sys.stderr)
    if misses:
        print(f"Missed {len(misses)} (no def; add inline in seed.txt to keep): "
              + ", ".join(misses), file=sys.stderr)


if __name__ == "__main__":
    main()
