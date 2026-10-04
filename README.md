# Calibre AI Library Manager

Give it an `.epub` or `.pdf`. It works out what the book really is (title, authors, ISBN, publisher, series, tags, rating, description), then adds it to your **Calibre** library by driving the Calibre desktop app through UI automation, with all the metadata filled in.

It is built for messy real-world files such as `Dune_03_-_Children_of_Dune_-_Frank Herbert.pdf` or `08cdbdec496f85d28a86c508f6f57e72.epub`, where the embedded metadata is missing, truncated or junk.

---

## Table of contents

1. [How it works (the big picture)](#1-how-it-works-the-big-picture)
2. [Input and output](#2-input-and-output)
3. [The extraction pipeline, step by step](#3-the-extraction-pipeline-step-by-step)
4. [The Calibre step](#4-the-calibre-step)
5. [Project structure](#5-project-structure)
6. [Installation](#6-installation)
7. [Getting the API keys](#7-getting-the-api-keys)
8. [Configuration](#8-configuration)
9. [Running it](#9-running-it)
10. [Handling different cases](#10-handling-different-cases)
11. [Reading the console report and `output.json`](#11-reading-the-console-report-and-outputjson)
12. [Troubleshooting](#12-troubleshooting)
13. [Extending the project](#13-extending-the-project)

---

## 1. How it works (the big picture)

```
 book file (.pdf / .epub)
        │
        ▼
 ┌─────────────────────────────┐
 │ STEP 1 - Metadata extraction│   src/metadata/
 │                             │
 │  1. embedded metadata       │
 │     (junk values rejected)  │
 │  2. first pages: text / OCR │
 │  3. ISBN found in the text  │
 │  4. LLM identifies the book │
 │  5. scrape Goodreads/Amazon │
 │     (scraped data WINS)     │
 │  6. LLM fills the gaps      │
 └──────────────┬──────────────┘
                │  BookMetadata (+ where each field came from)
                ▼
 ┌─────────────────────────────┐
 │ STEP 2 - Add to Calibre     │   src/calibre_ui/
 │  search library →           │
 │  add book / add format /    │
 │  skip → write metadata →    │
 │  verify                     │
 └──────────────┬──────────────┘
                ▼
        output.json + console report
```

The central design idea is **trust ordering**, and it has three rules:

1. **Distrust the file's own metadata.** Embedded values that look implausible are rejected up front (see `trust.py`), so they count as *missing* instead of poisoning the result.
2. **Real scraped data beats guesses.** Values scraped from Goodreads/Amazon **replace** whatever the embedded metadata or the LLM identification said, field by field. The LLM is used to *identify* the book and to fill what is still missing afterwards, not to overrule real data.
3. **What is printed in the book itself is the exception.** An ISBN found in the book's own text identifies *this* edition and is never replaced by a scraped one, and the file size always comes from the file.

Every field records its source (`file`, `text`, `ocr`, `llm`, `goodreads`, `amazon`, ...), so you can always see where a value came from.

---

## 2. Input and output

### Input

| What | Details |
|---|---|
| A book file | `.pdf` or `.epub`, passed as a path **relative to the project root** (`E:\Calibre`) or absolute |
| `--no-calibre` (optional flag) | Extract metadata only and do not touch Calibre |
| `.env` | API keys and optional settings (see [section 7](#7-getting-the-api-keys)) |
| `config/llm.yaml` | Which LLMs to use and in which order |
| `config/calibre_ui.yaml` | Calibre UI automation settings |

### Output

1. **Console report**: a summary of the extraction (file, text source, whether the LLM was used, which sites were scraped, timing), a table of all fields with their sources, any missing fields and errors, the first 2000 characters of the front text, and then a `CALIBRE` block (outcome, fields written, fields not set, verification).
2. **`output.json`** in the project root, containing the full extraction result (`res.to_dict()`: metadata, sources, scraped records, LLM raw answer, errors, and so on). When Calibre is used, the result of the Calibre step is added under the `"calibre"` key.
3. **A book in your Calibre library** (unless `--no-calibre`), with metadata set.
4. **`.cache/scrape/*.json`**: cached scraper responses (one JSON file per request, named by hash), so repeated runs do not hit Goodreads/Amazon again.

**Exit code:** `0` on success, `1` if extraction or the Calibre step failed. If only the Calibre step fails, the extracted metadata is still saved to `output.json`.

### The metadata fields

| Field | Notes |
|---|---|
| `title` | Replaced by the LLM's identification when it is confident |
| `authors` | List; same rule as the title |
| `isbn` | Checksum-verified when found in the text |
| `publisher`, `publish_date` | Usually from scrapers |
| `series` | **Optional**: legitimately empty for standalone books, so it never triggers an LLM call on its own |
| `tags` | Genres/subjects |
| `rating` | From Goodreads/Amazon |
| `comments` | The description/blurb |
| `file_size` | Always taken from the file itself (source `file`) |

---

## 3. The extraction pipeline, step by step

The algorithm lives in `src/metadata/extractor.py` (`BookMetadataExtractor`). Each format (`formats/epub.py`, `formats/pdf.py`) only implements two methods: `read_embedded()` and `read_front_text()`. Everything else is shared.

| # | Step | What happens |
|---|---|---|
| 1 | **Embedded metadata + file size** | Reads the metadata declared inside the file, then `sanitize()` cleans obvious junk (using the file name as a hint). Next, `distrust_embedded()` (in `trust.py`) **rejects implausible embedded values**, so they count as missing; each rejection is logged and recorded in `errors` as `embedded rejected: ...`. If reading fails, the error is recorded and the pipeline continues with empty metadata. |
| 2 | **Front text** | Reads the first **3 pages**. EPUBs and text PDFs use the text layer. Scanned PDFs go through OCR. The text source is reported as `text`, `ocr`, `mixed` or `none`. |
| 3 | **ISBN from the text** | Looks for an ISBN printed on the copyright page and checks its checksum. Only a valid ISBN is used. |
| 4 | **LLM identifies the book** | The LLM sees the file name, the embedded metadata and the first 6000 characters of the front text, and answers with title, authors and ISBN. Its title and authors **replace** the embedded values (which are often truncated or wrong). An ISBN it supplies only fills an empty slot (source `llm`). Discarded if its confidence is below `0.4`. |
| 5 | **Scrape Goodreads, then Amazon** | Searches by ISBN, or by title + authors. **Scraped data wins**: each scraped value replaces the existing one, field by field (details in [3.1](#31-how-scraped-data-wins-step-5-in-detail)). Runs even when nothing is missing. Stops once every wanted field has been decided, so the next site is never contacted for nothing. |
| 6 | **LLM completion** | Only runs if non-optional fields are still missing **after scraping**. The LLM fills the remaining gaps from the front text and only into empty fields. Discarded if confidence is below `0.4`. |

Rules that apply throughout:

- Steps 3 and 6 only **fill empty fields** (`meta.fill(field, value, source)` never overwrites).
- Step 4 deliberately replaces the embedded title/authors, because the LLM has looked at the actual title page.
- Step 5 deliberately replaces *everything* it can (except the protected fields below), but only when the scraped result is judged to be the same book.
- Every replacement still goes through `meta.fill()`, so the field's normalisation and validation apply. If `fill()` rejects the scraped value, the old value is restored.
- The LLM runs through the model chain in `config/llm.yaml`, and the first model that answers wins.
- Every failure is recorded in `errors` rather than crashing the run.

### Tunables (class attributes on `BookMetadataExtractor`)

| Attribute | Default | Meaning |
|---|---|---|
| `pages` | `3` | Leading pages read / OCR'd |
| `max_prompt_chars` | `6000` | Excerpt size sent to the LLM |
| `min_confidence` | `0.4` | LLM answers below this are ignored |
| `identify_first` | `True` | Always let the LLM identify title + authors first |
| `scraped_wins` | `True` | Scraped values replace embedded/identified ones. Set to `False` for the old behaviour where scraping only fills gaps |
| `scrape` | on | Disabled if env var `SCRAPE_DISABLED` is `1`, `true` or `yes` |

### 3.1 How scraped data wins (step 5 in detail)

With `scraped_wins = True` (the default), step 5 works like this:

**Which fields are touched.** Every field a scraper returns, except the protected ones. Empty values (`None`, `""`, `[]`, `0`) from a scraper are ignored, so a site can never blank out a field.

**Protected fields (never replaced by scraping):**

| Field | Why |
|---|---|
| `file_size` | Always read from the file itself |
| `isbn` (only when printed in the book) | An ISBN whose source is `text`, `ocr`, `mixed` or `embedded` identifies *this exact edition*. An ISBN that only came from the LLM (`llm`) is **not** protected and can be replaced by a scraped one. |

**Who decides each field.** Sites are tried in order (Goodreads, then Amazon). The **first site that provides a field decides it**; later sites cannot override it. If Goodreads has no publisher but Amazon does, Amazon fills the publisher.

**Same-book guard.** Because scraped data is allowed to overwrite your data, each result is first compared with the current title/authors. A result is ignored (and `scrape: <site> returned a different book, ignored` is added to `errors`) when:

- the titles do not match. Titles are compared after dropping a trailing `(...)` and anything after a `:`, so `Dust (Silo, #3)` and `Dust: A Novel` both become `dust`. They match if equal, if one starts with the other, or if they are at least 80% similar;
- or the authors share **no surname** (compared case-insensitively).

**Title cleaning.** Goodreads-style titles such as `Dust (Silo, #3)` are cleaned to `Dust` before being stored.

**Date safety.** A scraped `publish_date` that fails the plausibility check (`date_reason` in `trust.py`) is skipped, so one bad date is never traded for another.

**Early stop.** The loop ends as soon as all wanted fields (everything except `series` and the protected fields) have been decided by some scraper.

**Failures.** Any exception while scraping is caught and recorded as `scrape: ...` in `errors`; the extraction continues with what it has.

**Skipped entirely** when scraping is disabled (`SCRAPE_DISABLED`), or when there is no ISBN and no title + authors to search with.

> `series` is optional for the *completeness* check, but a scraper that does provide a series will still set it.

---

## 4. The Calibre step

`src/calibre_ui/` automates the Calibre desktop application on Windows through UI Automation (`pywinauto`). It does not use Calibre's command-line tools or its database.

For each book it:

1. Launches Calibre if it is not running (requires `calibre_exe`, see config) or attaches to the running window.
2. **Searches the library** for the book (title/author, `loose` or `exact` mode). The exact title + author match is always double-checked on the result table.
3. Decides what to do:

| Situation | Outcome |
|---|---|
| Book is not in the library | **Added** as a new book |
| Book exists, but not in this format (for example you have the EPUB and add the PDF) | The **missing format is added** to the existing book |
| Book exists with this format already | **Skipped** (no duplicates) |

4. Opens the **Edit metadata** dialog and writes the fields (title, authors, rating, tags, series, publisher, published date, ISBN, comments). Fields that cannot be set are reported under `Not set`.
5. If `verify_after_save` is on, searches again and confirms the book is present.

> **Do not touch the mouse or keyboard while this step runs.** It controls the real Calibre window.

---

## 5. Project structure

```
E:\Calibre
├── .env                       # your API keys (never commit this)
├── .env.example               # template for .env
├── requirements.txt
├── output.json                # written after every run
├── .cache/scrape/             # cached scraper responses
├── books/                     # your book files (any layout works)
├── config/
│   ├── llm.yaml               # LLM profiles + fallback chain
│   └── calibre_ui.yaml        # Calibre UI automation settings
└── src/
    ├── main.py                # entry point (CLI)
    ├── try_calibre_ui.py      # standalone script for testing the UI automation
    ├── metadata/              # STEP 1
    │   ├── extractor.py       # the shared pipeline
    │   ├── api.py             # build_extractor(...) factory
    │   ├── models.py          # BookMetadata, ExtractionResult
    │   ├── prompt.py          # LLM prompts + JSON schemas
    │   ├── validation.py      # cleans/validates LLM answers
    │   ├── cleaning.py        # sanitises embedded metadata
    │   ├── isbn.py            # ISBN finder + checksum
    │   ├── trust.py           # rejects implausible embedded values; date plausibility
    │   ├── fields.py
    │   └── formats/           # epub.py, pdf.py
    ├── ocr/                   # OCR for scanned PDFs
    │   ├── core.py, render.py, preprocess.py, config.py, models.py, errors.py
    │   └── engines/           # tesseract.py, ocrspace.py, llm_vision.py
    ├── llm/                   # provider-agnostic LLM client
    │   ├── client.py          # ask(prompt, schema=..., parse_json=True)
    │   ├── config.py          # reads llm.yaml
    │   └── providers.py       # Gemini / Groq / OpenAI
    ├── scrapers/              # Goodreads + Amazon
    │   ├── goodreads.py, amazon.py, http.py, match.py, models.py
    └── calibre_ui/            # STEP 2
        ├── client.py, session.py, workflow.py, matching.py, search_query.py
        ├── fields.py, formats.py, config.py, errors.py, models.py
        ├── pages/             # page objects: main_window, edit_metadata, file_dialog, table
        └── uia/               # low-level UI Automation helpers
```

---

## 6. Installation

### Requirements

- **Windows** (the Calibre step uses Windows UI Automation)
- **Python 3.13** (the project was developed on 3.13)
- **Calibre** desktop app installed: <https://calibre-ebook.com/download>
- **Tesseract OCR**, only needed to read scanned PDFs (see below)

### Steps

```powershell
cd E:\Calibre

# 1. (recommended) create a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. install dependencies
pip install -r requirements.txt

# 3. install the UI automation library used by the Calibre step
pip install pywinauto

# 4. create your .env
copy .env.example .env
# then edit .env and add your keys (section 7)
```

> **Note:** `pywinauto` is imported by the Calibre step (`main.py` imports it lazily so `--no-calibre` works without it) but is **not currently listed in `requirements.txt`**. Add a `pywinauto` line to that file so a fresh install works.

### Tesseract (for scanned PDFs)

1. Download the Windows installer from the UB Mannheim builds: <https://github.com/UB-Mannheim/tesseract/wiki>
2. Install it (default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`).
3. Set `TESSERACT_CMD` in `.env` to that path, or add the folder to your `PATH`.

If you do not install Tesseract, the project can still use the `ocrspace` or `llm_vision` OCR engines (see [OCR engines](#ocr-engines)).

---

## 7. Getting the API keys

You do **not** need all of them. The LLM layer tries the models listed in `fallback` in order, so one working key is enough to start. Free tiers exist for Gemini and Groq. Keys go in `.env`, never in `llm.yaml`.

| Variable | Used for | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | Gemini LLM (first in the fallback chain) | Google AI Studio: <https://aistudio.google.com/apikey> |
| `GROQ_API_KEY` | Groq LLM (the configured `default`) | Groq Console: <https://console.groq.com/keys> |
| `OPENAI_API_KEY` | OpenAI LLM (last fallback) | OpenAI Platform: <https://platform.openai.com/api-keys> |
| `OCR_API_KEY` | OCR.space cloud OCR engine (optional) | <https://ocr.space/ocrapi> (free key sent by email) |
| `TESSERACT_CMD` | Path to `tesseract.exe` (optional if on `PATH`) | Installed locally, see above |
| `SCRAPE_SOURCES` | Which sites to scrape, in order | Not a key: `goodreads,amazon` |

Example `.env`:

```dotenv
GEMINI_API_KEY=your-gemini-key
GROQ_API_KEY=your-groq-key
OPENAI_API_KEY=
OCR_API_KEY=
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
SCRAPE_SOURCES=goodreads,amazon
```

Optional env var read by the extractor:

```dotenv
SCRAPE_DISABLED=1    # skip Goodreads/Amazon entirely (1 / true / yes)
```

**Security:** `.env` contains secrets. Add it to `.gitignore` and never share it.

---

## 8. Configuration

### `config/llm.yaml`

```yaml
default: groq            # model used when you name none

fallback:                # tried in this order; first success wins
  - gemini
  - groq
  - openai

models:
  gemini: { provider: gemini, model: ..., api_key_env: GEMINI_API_KEY, temperature: 0 }
  groq:   { provider: groq,   model: ..., api_key_env: GROQ_API_KEY,   temperature: 0, base_url: https://api.groq.com/openai/v1 }
  openai: { provider: openai, model: ..., api_key_env: OPENAI_API_KEY, temperature: 0 }
```

- Each entry under `models` is a named profile. `api_key_env` is the **name of the environment variable**, not the key itself.
- `temperature: 0` keeps the answers as deterministic as possible, which is what you want for metadata.
- A provider whose key is missing or whose call fails is skipped, and the next one in `fallback` is tried.
- **Check the `model:` names** in your copy of the file against what each provider currently offers. A mistyped or retired model name is the most common reason an LLM profile fails. Provider model lists: [Gemini](https://ai.google.dev/gemini-api/docs/models), [Groq](https://console.groq.com/docs/models), [OpenAI](https://platform.openai.com/docs/models).
- To add a provider, add a profile under `models` and append it to `fallback`.

### `config/calibre_ui.yaml`

All keys are optional.

| Key | Default | Meaning |
|---|---|---|
| `calibre_exe` | `null` | Full path to `calibre.exe`, for example `C:\Program Files\Calibre2\calibre.exe`. Set it if you want the tool to launch Calibre itself. |
| `window_title_re` | `'^calibre\s*[—–-]\s*\|\|'` | Regex matching the main window title (`calibre — \|\| Calibre Library \|\|`) |
| `edit_dialog_title_re` | `'^Edit metadata'` | Regex for the metadata dialog title |
| `launch_timeout` | `60` | Seconds to wait for Calibre to start |
| `dialog_timeout` | `20` | Seconds to wait for a dialog to open/close |
| `action_timeout` | `10` | Seconds for individual UI actions |
| `add_timeout` | `90` | Seconds to wait for a newly added book to appear |
| `search_mode` | `loose` | `loose`: title/author "contains" search. `exact`: `title:"=..."` equality search |
| `search_settle` | `0.6` | Seconds to let the table refresh after a search |
| `date_format` | `'%b %Y'` | How your Calibre displays the "Published" date (for example `Apr 2013` → `%b %Y`) |
| `add_format_button` | `auto` | Which button adds a format: `auto`, `top_left`, `top_right`, `bottom_left`, `bottom_right` |
| `skip_fields` | `[]` | Fields never written, for example `[rating, comments]` |
| `verify_after_save` | `true` | Search again after saving to confirm |
| `key_pause` | `0.01` | Delay between keystrokes (keyboard fallback only) |
| `ui_text` | `{}` | Override UI strings if Calibre/Windows is **not in English** |

### OCR engines

Located in `src/ocr/engines/`:

| Engine | Needs | Notes |
|---|---|---|
| `tesseract` | Tesseract installed + `TESSERACT_CMD` | Local, free, offline |
| `ocrspace` | `OCR_API_KEY` | Cloud service, useful if you do not want to install Tesseract |
| `llm_vision` | An LLM key with vision support | Uses a vision-capable model to read the page image |

OCR is only triggered when the PDF has no usable text layer. Page images are rendered with `pypdfium2` and cleaned up with Pillow before recognition.

---

## 9. Running it

Always run from the project root (`E:\Calibre`).

```powershell
# Full run: extract metadata, then add to Calibre
python src/main.py "books/Silo/Wool/Wool_-_Hugh_Howey.pdf"

# Extraction only (no Calibre, no pywinauto needed)
python src/main.py "books/Silo/Wool/Wool_-_Hugh_Howey.epub" --no-calibre
```

Paths are resolved relative to the project root, and absolute paths also work.

### Recommended first run

1. Run with `--no-calibre` on one book and inspect the report and `output.json`. Check that the title, authors and ISBN look right.
2. Open Calibre, close any open dialogs, and leave the window visible.
3. Run again without `--no-calibre`, hands off the mouse and keyboard.

### Process several books

`main.py` handles one book per run. To process a folder, loop in PowerShell:

```powershell
Get-ChildItem books -Recurse -Include *.pdf,*.epub | ForEach-Object {
    python src/main.py $_.FullName
}
```

`output.json` is overwritten on every run, so redirect the console output (`*> log.txt`) or copy `output.json` after each book if you want to keep every result.

### Testing the UI automation alone

`src/try_calibre_ui.py` is a standalone script for exercising the Calibre automation without running extraction. Use it when the Calibre step misbehaves and you want to isolate the problem.

---

## 10. Handling different cases

| Case | What happens | What you can do |
|---|---|---|
| **Clean EPUB with good metadata** | Embedded metadata passes the trust check, the LLM confirms title/authors, and scraped values then replace or complete them (Goodreads/Amazon win) | Nothing |
| **Implausible embedded metadata** (nonsense title, impossible date, ...) | Rejected by `trust.py`, treated as missing, and noted as `embedded rejected: ...` in `errors` | Nothing; the value is re-derived from the text, LLM and scrapers |
| **EPUB/PDF with junk or truncated title** (for example `The_Shock_Doctrine__The_Rise_of_Disaster_C_...`) | The LLM reads the title page and replaces the title and authors | Nothing |
| **Scanned PDF (no text layer)** | Front pages are OCR'd (`Text from: ocr`) | Install Tesseract or set `OCR_API_KEY` |
| **Mixed PDF** | `Text from: mixed`: some pages have text, some needed OCR | Nothing |
| **No text at all** (`Text from: none`) | The ISBN and LLM steps have little to work with, so the result falls back to embedded metadata and the file name | Fix OCR setup; check that the file is not corrupt or DRM-protected |
| **ISBN printed in the book** | Verified by checksum, used for precise scraping, and **protected**: a scraped ISBN never replaces it | Nothing |
| **ISBN only guessed by the LLM** | Used to search, but a scraped ISBN may replace it | Nothing |
| **No ISBN found** | Scraping uses title + authors | Nothing |
| **No ISBN and no title + authors** | Scraping is skipped (`scrape: skipped, need an ISBN or title + authors`) and only the LLM can fill gaps | Rename the file clearly, or improve OCR |
| **LLM not confident** (below 0.4) | Its answer is discarded and noted in `errors`; embedded values stay | Try another model first in `fallback`, or check the front text in the report |
| **LLM provider down / key missing** | The next provider in `fallback` is tried | Add more keys; check model names in `llm.yaml` |
| **All LLMs fail** | `errors` records it. Identification falls back to the embedded values, and scraping still runs if there is an ISBN or title + authors | Fix keys, then re-run |
| **Scraper returns a different book** | The result is ignored (`scrape: <site> returned a different book, ignored`) and your values stay | If it keeps happening, check that the title/authors in the report are correct |
| **Scraped data is worse than yours** | Scraped data still wins | Set `scraped_wins = False` in the extractor to only fill gaps, or add the field to `skip_fields` for Calibre |
| **Goodreads/Amazon blocks or changes layout** | That source contributes nothing and the other is tried | Set `SCRAPE_SOURCES` to the working site, or clear `.cache/scrape` |
| **Scraping not wanted** | Skips step 5; embedded/identified values are kept and the LLM fills the rest | `SCRAPE_DISABLED=1` in `.env` |
| **Standalone book** | `series` stays empty (this is not an error) | Nothing |
| **Series book** (for example Dune, Silo) | `series` filled from scrapers or LLM | Verify the series index in Calibre afterwards |
| **Same book, same format already in Calibre** | **Skipped** | Nothing |
| **Same book, different format** (EPUB then PDF) | The format is **added to the existing book** | Nothing |
| **Calibre not running** | Launched if `calibre_exe` is set, otherwise the step errors | Set `calibre_exe` or open Calibre first |
| **Non-English Calibre / Windows** | Buttons and labels are not found | Fill `ui_text` in `calibre_ui.yaml` |
| **Different date display in Calibre** | The Published date is written in the wrong format | Set `date_format` to match your Calibre |
| **Do not want some fields overwritten** | Fields are written to Calibre | List them in `skip_fields` |
| **Calibre step fails** | Metadata is still saved to `output.json` with `"calibre": {"error": ...}`, exit code `1` | Fix the cause and re-run (cached scrapes make this fast) |

---

## 11. Reading the console report and `output.json`

Example console report (abridged):

```
========================================================================
File      : E:\Calibre\books\Silo\Wool\Wool_-_Hugh_Howey.pdf
Text from : text   (first 3 pages)
LLM       : used, confidence 0.90
Scraped   : goodreads
Time      : 8.4s
------------------------------------------------------------------------
title        Wool                                      [llm]
authors      Hugh Howey                                [llm]
file_size    2,431,552 bytes                           [file]
rating       4.17                                      [goodreads]
isbn         978...                                    [text]
...
Missing   : none
CALIBRE
Outcome   : added  (PDF)
Written   : title, authors, rating, tags, ...
Verified  : yes, found again after saving
```

*(Numbers above are illustrative.)*

How to read it:

- **`[source]` tags** show where each value came from: `file` (file system), `text`/`ocr` (printed in the book), `llm`, or a scraper name (`goodreads`, `amazon`). Because scraped data wins, most fields normally end up tagged with a scraper name; `title`/`authors` tagged `llm` mean no scraper supplied them (or the scraper was ignored as a different book).
- **`(missing)`** means no source could supply the field.
- **`Missing:`** lists fields still empty at the end (`series` can legitimately appear here).
- **`Error:`** lines are non-fatal problems collected during the run.
- **`FRONT TEXT`** shows what the LLM actually saw. If the title page is garbage here, the OCR or text extraction is the problem, not the LLM.

Top-level keys of `output.json` come from `ExtractionResult.to_dict()`: the metadata with its sources, `text_source`, `identity` (the LLM's identification), `scraped` (raw records from each site), `llm_used` / `llm_confidence` / `llm_raw`, `errors`, and, after the Calibre step, `calibre`.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ModuleNotFoundError: pywinauto` | `pip install pywinauto` (and add it to `requirements.txt`), or use `--no-calibre` |
| `ModuleNotFoundError: metadata` or `scrapers` | Run from `E:\Calibre` with `python src/main.py ...` so `src/` is on the path |
| `FileNotFoundError: Book file not found` | Check the path and quotes; paths with spaces need double quotes |
| `identify: book not recognised with enough confidence` | The front text is poor or the model is weak. Look at the `FRONT TEXT` section, try a different first model in `fallback` |
| `llm: ...` errors with 401/403 | Wrong or missing API key in `.env`, or the key variable name does not match `api_key_env` |
| `llm: ...` errors with 404 / model not found | The `model:` name in `llm.yaml` is wrong or retired for that provider |
| `llm: ...` errors with 429 | Rate limit hit; wait, or reorder `fallback` |
| OCR returns nothing | `TESSERACT_CMD` wrong or Tesseract not installed; try `ocrspace` |
| `scrape: skipped...` | Not enough information to search; see [section 10](#10-handling-different-cases) |
| `scrape: <site> returned a different book, ignored` | The same-book guard rejected the result (title or author surname mismatch). Check the title/authors in the report; a wrong identification in step 4 is the usual cause |
| `embedded rejected: ...` | Informational: the file's own metadata failed the plausibility check in `trust.py` and was discarded |
| Title/authors look wrong after a run | Check whether they came from a scraper (`[goodreads]`) or `[llm]`; a wrong scraper match that slipped past the guard can be fixed by clearing `.cache/scrape` or setting `scraped_wins = False` |
| Scraped data looks stale or wrong | Delete the relevant file(s) in `.cache/scrape/` (or the whole folder) and re-run |
| Calibre window not found | `window_title_re` does not match your window title; compare it to the real title bar |
| Book added but fields empty | Check `Not set:` lines in the report; `date_format` and `ui_text` are the usual culprits |
| UI automation clicks the wrong thing | Do not use the PC during the run; set `add_format_button` explicitly instead of `auto` |
| Unicode errors in the console | `main.py` already reconfigures stdout to UTF-8; use Windows Terminal if the font lacks glyphs |

Increase detail by changing `logging.basicConfig(level=logging.INFO, ...)` in `main.py` to `logging.DEBUG`.

---

## 13. Extending the project

- **New book format** (for example `.mobi`, `.azw3`): add `src/metadata/formats/<fmt>.py` with a subclass of `BookMetadataExtractor` implementing `read_embedded()` and `read_front_text()`, then register it in the `build_extractor` factory in `api.py`.
- **New scraper** (for example Google Books, Open Library): add a module in `src/scrapers/`, register it in `iter_sources`, and add its name to `SCRAPE_SOURCES`.
- **New LLM provider**: add it to `providers.py` and give it a profile in `llm.yaml`.
- **Change what gets sent to the LLM**: edit `src/metadata/prompt.py` (prompts and JSON schemas) and `validation.py` (how answers are cleaned).
- **Tune behavior**: `pages`, `max_prompt_chars`, `min_confidence`, `identify_first` and `scraped_wins` are class attributes on `BookMetadataExtractor`.
- **Change what counts as junk metadata or a bad date**: edit `src/metadata/trust.py` (`distrust_embedded`, `date_reason`).
- **Change which printed ISBN sources are protected**: edit `PRINTED_ISBN_SOURCES` in `extractor.py`.
- **Loosen or tighten the same-book guard**: edit `_same_book` / `_title_key` in `extractor.py` (title similarity threshold is `0.8`; authors must share a surname).

---

## Notes

- Scraping Goodreads and Amazon may be subject to those sites' terms of service. Keep usage personal and low-volume, which the scrape cache helps with.
- Always keep a backup of your Calibre library before running automated batch imports.