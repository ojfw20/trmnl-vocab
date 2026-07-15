# trmnl-vocab

A private [TRMNL](https://usetrmnl.com) plugin that shows a fresh vocabulary word
every few minutes, instead of the once-a-day Word of the Day. It teaches a mixed
bag of genuinely useful words: the unusual-but-usable, the literary, and the ones
with a good story behind them.

## How it works

The stock Word of the Day plugin is locked to refresh once a day. This gets round
that with a plugin that picks a new word on every render:

- `words.json` is a flat list of words (definition, pronunciation, part of speech),
  served from GitHub raw and polled by TRMNL every 5 minutes.
- The Liquid markup picks a pseudo-random entry each render, keyed off the
  nanoseconds of the current time, so a new word appears on every refresh.
- TRMNL rejects a polling response over ~100 KB, so the live `words.json` is a
  random subset of a larger master pool. A weekly GitHub Action reshuffles that
  subset, so the words on show slowly rotate over time.

No server to run: it is a static file plus a scheduled reshuffle.

## Files

| File | What it is |
|---|---|
| `seed.txt` | The curated word list (one per line). The thing you edit to change words. |
| `build.py` | Enriches the seed with definitions/IPA/examples from the Free Dictionary API → `words.master.json`. |
| `words.master.json` | The full built pool. |
| `publish.py` | Picks a random subset under the size cap → `words.json` (the live file). |
| `words.json` | What the device actually polls. |
| `src/*.liquid` | The plugin markup for each layout (quadrant is the one used in the mashup). |
| `.github/workflows/reshuffle.yml` | Weekly job that reshuffles `words.json`. |

## Changing the words

Edit `seed.txt` (a plain word per line; `word | inline definition | type` for
coined words the dictionary API doesn't carry), then:

```sh
python3 build.py      # fetch/refresh definitions into words.master.json (cached; resumable)
python3 publish.py    # pick the live subset into words.json
git commit -am "Update words" && git push
```

`build.py` caches every API lookup in `cache.json`, so reruns are instant and it
resumes if the free API rate-limits it.

## Deploy to your TRMNL

The plugin is a standard trmnlp project, so the easiest path is to push it:

```sh
gem install trmnl_preview     # or use the Docker image
trmnlp login                  # paste your TRMNL API key
trmnlp push                   # creates/updates the "Vocabulary" private plugin
```

Or set it up by hand in the TRMNL web UI:

1. **Plugins → Private Plugin → Add new.** Name it `Vocabulary`, strategy **Polling**.
2. **Polling URL:** `https://raw.githubusercontent.com/ojfw20/trmnl-vocab/main/words.json`
   (verb GET, no headers). Save.
3. **Edit Markup:** paste the contents of `src/quadrant.liquid` into the Quadrant
   tab (and `full`/`half_*` into their tabs if you want them).
4. **Refresh rate:** 5 minutes (needs TRMNL+; the free floor is 15).
5. **Mashup:** in Playlists, open your quadrant mashup and set the top-right slot
   to `Vocabulary`, replacing Word of the Day. Retire the old plugin.

## Preview locally

```sh
trmnlp serve                              # live preview at localhost:4567
trmnlp build --png                        # render each layout to PNG
```

Offline previews use the sample words in `.trmnlp.yml`; comment that block out to
fetch the live `polling_url` instead.
