# inCraw

Give it LinkedIn people (profile URLs, names, or a CSV) and it tells you, for each one, whether they are **Open to Work**.

It drives a real Chrome window signed in to *your* LinkedIn account, opens each profile the way a person would, and reads what LinkedIn shows.

## Setup (once)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
```

inCraw uses your installed Google Chrome. If Chrome isn't installed, run `.venv\Scripts\python -m playwright install chromium` and it falls back to Chromium.

## Use

```powershell
start.bat                      # or: .venv\Scripts\python -m incraw serve
```

The UI opens at http://127.0.0.1:8765. Click **Log in to LinkedIn** and sign in in the Chrome window that opens. The session is saved in `.browser-profile/`, so you only do this again when LinkedIn logs you out.

Paste people one per line:

```
https://www.linkedin.com/in/some-profile/
Jan Kowalski, Allegro        <- name + company (company is optional but helps a lot)
Anna Nowak | CD Projekt
```

You can also paste a CSV with `url` / `name` / `company` columns. Results appear live, and **Export CSV** downloads the batch.

Without the UI:

```powershell
.venv\Scripts\python -m incraw login
.venv\Scripts\python -m incraw check people.txt --out results.csv
```

## What the results mean

| Status | Meaning |
|---|---|
| **Open to work** | LinkedIn's own signal is public: the #OpenToWork photo frame and/or the "Open to work" card on the profile. The roles they want are captured when shown. |
| **Likely** | Only the headline says it ("looking for new opportunities", "otwarty na nowe oferty", ...). |
| **Not detected** | Nothing public. |
| **Ambiguous** | A name matched several people. Click **Check** on the right one. |
| **Not found / Unavailable** | No search match, or the profile can't be viewed from your account. |

**What it can't see:** a member can set Open to Work to *Recruiters only*. That is visible only to LinkedIn Recruiter seat holders, not to normal accounts, so those people come out as **Not detected**. "Not detected" means "not publicly open to work", not "not looking".

## Staying under the radar

Automating LinkedIn is against its User Agreement, and accounts that browse like bots get restricted. inCraw paces itself:

- one profile at a time, with a random 8-20 s gap between page loads, scrolling like a reader
- a daily cap of 120 page loads (a name costs 2: one search, one profile)
- results less than 7 days old are reused instead of reloaded
- if LinkedIn shows a security check, inCraw pauses. Solve it in the Chrome window, then click **Resume**.

Override with environment variables: `INCRAW_DELAY_MIN`, `INCRAW_DELAY_MAX`, `INCRAW_DAILY_CAP`, `INCRAW_CACHE_DAYS`, `INCRAW_HEADLESS=1`.

## Layout

| | |
|---|---|
| `incraw/detect.py` | the Open-to-Work rules: photo frame, profile card, headline phrases (EN + PL) |
| `incraw/linkedin.py` | Chrome session, page extraction (all LinkedIn DOM knowledge lives here) |
| `incraw/resolve.py` | name → profile matching and the auto-pick rule |
| `incraw/engine.py` | the background worker: queue, pacing, daily cap, pause/resume |
| `incraw/store.py` | SQLite at `data/incraw.db` |
| `incraw/web.py`, `incraw/static/` | the local UI |

If LinkedIn changes its page and results start looking wrong, adjust `EXTRACT_PROFILE_JS` in `linkedin.py` or the rules in `detect.py`. Tests: `.venv\Scripts\python -m pytest`.

`data/` (results) and `.browser-profile/` (your LinkedIn cookies) are git-ignored. Keep it that way.
