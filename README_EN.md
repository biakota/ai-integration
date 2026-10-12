# vadiMAP — Backend / AI Integration Take-Home

*Version française : [README_FR.md](./README_FR.md)*

Welcome, and thank you for taking the time. A suggested pacing
(~3h45 total) is in the **Tickets** section below — guidelines, not hard
rules. If you find yourself going significantly over, stop and write down
what you would have done next in your `NOTES.md`.

## On AI tools

We use AI heavily in our day-to-day work and don't discourage you from
using it here. What we review is your final code and your `NOTES.md` — not
how you got there. If AI lets you finish quickly, use the slack to slow
down: plan, push back on suggestions that don't feel right, and sketch
alternatives in your notes.

Our codebase predates LLMs, so a lot of our work is reshaping code written
without AI. Candidates who can flag a problem, sketch how they'd address
it, and accept that the actual fix might belong in a follow-up PR fit our
reality better than candidates who reach for a rewrite.

## Context

vadiMAP helps building owners plan energy retrofits. To do that we need
their **utility bills** — electricity, gas — turned into structured data:
billing period, consumption, amounts. Today a person types them in by hand.

This repo is a tiny Django + React app modelled on ours:

- A **building** has **bills** — one per utility account (its Hydro-Québec
  electricity, its gas, …).
- A bill has **entries**, one per billing period: a year of bills is
  typically 6 bimonthly or 12 monthly entries.

A user can already **upload** a bill file, which adds an entry to one of a
building's bills, **enter** an entry manually, and **review** entries.
Uploads go through a parsing pipeline — but no parser exists yet, so every
uploaded entry ends up `unparsed`. Your job is to make the app actually
read bills.

```
backend/    Django 5 + DRF, SQLite, seeded with users, buildings and a year of bills
frontend/   React (Vite, JS) — provided, you shouldn't need to touch it
samples/    Synthetic sample bills + ground_truth.json
```

## ⚠️ Personal information — a hard constraint

Utility bills contain personal information. Our company policy, which is
stricter than what Québec's Law 25 requires:

> **No personal information may be sent to a third-party service** — hosted
> LLM APIs and hosted OCR APIs included.

What counts as personal information on a bill, where it flows in this
app, and how you *guarantee* the rule holds are part of the exercise.
Hosted models aren't forbidden — sending them personal information is.

The sample bills are synthetic — made-up people, addresses, accounts and
amounts — but **treat them as if they were real customer bills.**

## Setup

You will need **Python 3.11+** and **Node 20+**.

### macOS / Linux / WSL

```bash
./setup.sh        # .env, venv, deps, migrations, seed, npm install
```

Then, in two terminals:

```bash
# Terminal 1 — backend on http://localhost:8000
cd backend && source .venv/bin/activate && python manage.py runserver

# Terminal 2 — frontend on http://localhost:5173
cd frontend && npm run dev
```

### Windows (PowerShell)

```powershell
.\setup.ps1
```

```powershell
# Terminal 1
cd backend; .\.venv\Scripts\Activate.ps1; python manage.py runserver

# Terminal 2
cd frontend; npm run dev
```

> WSL works too — follow the macOS / Linux instructions inside your WSL shell.

> Installing by hand instead of with the script? After `pip install -r
> requirements.txt`, also run the two OpenCV lines from `setup.sh`: they
> swap in OpenCV's headless build, which the OCR needs on Linux / WSL.

Open http://localhost:5173. The Vite dev server proxies `/api/*` and
`/media/*` to Django. If port 8000 is taken, run Django on another port
(`python manage.py runserver 8001`) and start Vite with
`BACKEND_URL=http://localhost:8001 npm run dev`. Run the tests with `python manage.py test` from
`backend/`.

### Authentication and seeded data

DRF token auth with the `Bearer` keyword; `POST /api/auth/login/` with
`{"username", "password"}` returns a token. The "Acting as" dropdown in the
header logs you in as one of the seeded users: `admin` (superuser),
`alice`, `bob` — **all with password `takehome`**.

The database is seeded with **3 buildings** (2 for Alice, 1 for Bob), each
with a year of manually-entered bill entries, to show what the data looks
like. To demo your work, **create a new building** from the home page, add
a bill to it, and upload the samples there.

Swagger UI is at http://localhost:8000/api/docs/ (click "Authorize" and
paste the raw token). Django admin at http://localhost:8000/admin/.

> **Out of scope:** login forms, registration, token expiry, changing the
> seeded users (the frontend hardcodes them).

## How the app works today

| Endpoint | What it does |
|---|---|
| `GET /api/buildings/` | Your buildings, with a summary of their bills. |
| `POST /api/buildings/` | Create a building you own. |
| `GET /api/buildings/{id}/` | One building, its bills and all their entries. |
| `POST /api/buildings/{id}/bills/` | Add a bill (utility account) to a building. |
| `POST /api/bills/{id}/upload/` | Multipart, one or more `files` (one PDF, or one image per page). Stores them in a new entry, runs the parsing pipeline, returns the entry. |
| `POST /api/bills/{id}/entries/` | Manual entry. Creates a `confirmed` entry with `source=manual`. |
| `GET /api/entries/{id}/` | One entry, with its documents. |
| `PUT /api/entries/{id}/` | A human corrects an extracted entry → `confirmed`. |

On an entry, `end_billing_period` is **exclusive** (a period billed from
January 1st to January 31st ends on February 1st, so `end − start` is the
number of days billed) and `bill_cost` is the cost **before taxes**.

The pipeline lives in `backend/bills/`:

- `services.process_upload()` — extracts the PDF text layer, builds a
  `DocumentInput` per file, runs the parsers, copies the result onto the
  `BillEntry` (and fills the bill's account number / rate if empty), and
  sets the entry's status.
- `parsing/base.py` — `DocumentInput`, `ParsedEntry` and the `BillParser`
  protocol. `parsing/registry.py` — the ordered `PARSERS` list (empty
  today).
- `extraction/ocr.py` — a ready-made **local OCR helper** (RapidOCR, runs
  on your machine): `ocr_lines(image)` returns a page's text lines, top to
  bottom, straightened for slightly rotated photos; `pdf_page_images(path)`
  renders a PDF's pages (for scans with no text layer). Not wired into the
  pipeline. The first call takes a few seconds (model loading), then a few
  seconds per page.
- `ai/client.py` — a small `LLMClient` interface and a `FakeLLMClient`
  that returns canned answers and **records every request it receives**.
  `get_llm_client()` picks the client from `AI_PROVIDER` in `.env`.

An entry's `status` drives the review UI: `unparsed` (nothing could read it),
`needs_review` (extracted, a human should check), `parsed` (extracted, trusted),
`confirmed` (checked by a human). `source` says who filled it:
`manual`, `deterministic` or `ai`.

These shapes are a starting point. Change them if your design needs it —
just keep the fields the frontend displays, and say why in `NOTES.md`.

### Samples

`samples/ground_truth.json` lists every sample with its expected values —
account-level fields under `bill`, the billing period under `entry` —
(canonical forms: ISO dates, `"1234.56"` decimal strings, account numbers
without separators) and the personal information printed on it.

- `hydro-quebec/pdf/` — **synthetic** Hydro-Québec bills we generated: they
  reproduce the layout of Hydro-Québec's public specimens, with a text layer
  like the PDFs downloaded from the customer portal, but every value is made
  up. Plus one scanned PDF with no text layer.
- `hydro-quebec/images/` — the same synthetic bills as a screenshot and as a
  phone photo (one image per page).
- `hydro-quebec/specimens/` — Hydro-Québec's **official** public specimen
  bills, from hydroquebec.com. Placeholders instead of values; layout
  reference only.
- `other-utilities/` — synthetic bills from two **fictional** utilities with
  different layouts.

We provide the OCR helper because writing OCR plumbing says little about
your judgment these days. Use it, replace it, or ignore it — what we look
at is what you do with its output.

## Tickets

### Suggested pacing

- Reading + setup: ~30 min
- Ticket 1: ~75 min
- Ticket 2: ~90 min
- Ticket 3 + `NOTES.md`: ~30 min

### Overview

- **Tickets 1 and 2 are required** — please implement both.
- **Ticket 3 is written only**, in `NOTES.md`.

Please commit between tickets so we can see your progression. If something
is ambiguous, **make a reasonable choice and document it in `NOTES.md`**.

**Fixing bugs in the existing code is out of scope.** That said, a good
teammate documents any finding or concern they have about the code they
work in — please list yours in `NOTES.md`.

### Ticket 1 — Deterministic Hydro-Québec reader

Hydro-Québec bills downloaded from the portal are PDFs with a text layer
and a stable layout. Reading them doesn't need a model.

Build a deterministic parser for Hydro-Québec PDF bills and plug it into
the pipeline, so that uploading one of `samples/hydro-quebec/pdf/` fills
the entry with `source=deterministic`.

- It must extract the fields correctly for every Hydro-Québec PDF
  sample that has a text layer — check them against `ground_truth.json`
  **in tests**.
- It must **decline** what it can't read (other utilities, scans, …)
  instead of guessing, so the next parser gets a chance.
- Decide when a result is trusted (`parsed`) versus `needs_review`, and
  explain the rule.

### Ticket 2 — Everything else, with a model

The deterministic reader can't handle photos, scans or other utilities.
Add an extraction path that uses a model — your choice of approach:
hosted or local model, OCR + LLM, vision model, or a mix.

- **The personal-information constraint above applies.** Show how your
  design guarantees it, and prove it with a test.
- Don't trust the model blindly: decide what you check before accepting
  its output, and what happens when it's wrong or unsure.
- Our samples won't cover every utility. **We encourage you to find your
  own**: many utilities publish annotated specimen bills ("how to read your
  bill"), in Québec, elsewhere in Canada, in the US or in France. Trying
  your design on a layout you didn't build it for tells you a lot — tell us
  what you tried and what you learned. Use public specimens only, never a
  real person's bill.
- **Your submission must run, and its tests pass, with `AI_PROVIDER=fake`**
  — we'll review it without any API key.
- We don't provide an API key and **you're not expected to spend any
  money**. Designing and testing against the fake client is a complete
  answer. If you want to try a real model for free, the simplest option is
  a **local model with [Ollama](https://ollama.com)** — e.g.
  `ollama pull qwen2.5:7b` (≈ 5 GB), served on `http://localhost:11434`.
  It runs without a GPU, but slowly: on a laptop CPU expect 1–2 minutes
  per bill, so try a few samples rather than all of them. A provider's free
  tier or a key you already have is fine too, as long as the
  personal-information rule holds. Either way, tell us which model, how it
  did on the samples, and what it would roughly cost per bill.

### Ticket 3 — Production *(written only)*

In `NOTES.md`, a page at most. Suppose this goes live for thousands of
bills a month:

- **Personal-information data flow:** where does it live, who can see it,
  what leaves our infrastructure, how long do we keep what?
- How would you **run** extraction (sync vs async, retries, timeouts)?
- How would you know it's **still accurate** in six months, when a utility
  changes its layout?
- When is it worth writing another deterministic parser instead of
  relying on the model?

## Source control

Please use git — we ask for the history so we can follow your thought
process. `git init` at the start and commit as you go. A layout we'd find
easy to read: one branch per ticket (`ticket-1`, `ticket-2`) and a `final`
branch with everything.

## Deliverables

- Your code as a zip — **please include your `.git/` directory**. Leave out
  `.env`, `node_modules/`, `.venv/`.
- A `NOTES.md` covering:
  - **Decisions** you made where the spec was ambiguous
  - Any **findings or concerns** about the existing code
  - **What you'd push back on** if this were a real ticket
  - **What you'd do next** with more time
  - Ticket 3
  - Roughly how long you spent

We do **not** expect perfection — we expect taste. Have fun.
