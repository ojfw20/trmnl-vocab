#!/usr/bin/env python3
"""Publish words.json — a random subset of words.master.json for the device.

TRMNL rejects a polling response over ~100 KB, so we pick a random subset that
stays under a safety budget (and no more than --max entries). Running this on a
schedule reshuffles which words are live, so the set rotates over time without
any always-on server. Output is minified.
"""
import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
MASTER = HERE / "words.master.json"
OUT = HERE / "words.json"


def minified(words):
    return json.dumps({"words": words}, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=600, help="max entries to publish")
    ap.add_argument("--budget", type=int, default=97000, help="max bytes (UTF-8)")
    ap.add_argument("--seed", type=int, default=None, help="fix RNG for a reproducible pick")
    args = ap.parse_args()

    master = json.loads(MASTER.read_text(encoding="utf-8"))["words"]
    rng = random.Random(args.seed)
    pool = master[:]
    rng.shuffle(pool)

    chosen = []
    for w in pool:
        if len(chosen) >= args.max:
            break
        trial = chosen + [w]
        if len(minified(trial).encode("utf-8")) > args.budget:
            continue  # skip this one, a shorter later entry may still fit
        chosen = trial

    chosen.sort(key=lambda w: w["word"].lower())  # stable order -> readable diffs
    blob = minified(chosen)
    OUT.write_text(blob + "\n", encoding="utf-8")
    size = len(blob.encode("utf-8"))
    print(f"Published {len(chosen)}/{len(master)} words to {OUT.name} "
          f"({size} bytes, {size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
