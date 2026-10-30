# Sheep Heaven ERP — Scope Document

**Version:** 0.3
**Date:** 2026-10-30
**Location:** `erp/`
**Status:** Core decisions made (Section 13). Remaining open items in Section 14.

---

## 1. Purpose

Sheep Heaven ERP is a farm management system for a **sheep breeding-stock operation**. Its core job is to
keep a complete, trustworthy life record of every animal on the farm, identified by its RFID ear tag, from
the day it is born or enters the farm until the day it leaves (sold, died, culled).

Around that record it tracks weight, age, photos, health, breeding, pedigree, pen movements, feed and
other costs, and sales, so the farmer can answer:

- Which animals do I have right now, where are they, and how old are they?
- How is each animal growing? How much weight did the herd gain this month, this year?
- Which ewes are pregnant, when are they due, and how did their last lambing go?
- What is this animal's lineage? Which rams and ewes produce the best offspring?
- What does the herd cost me per day in feed? What did I spend this month, on what?
- What did this animal cost from entry to sale, what did it sell for, and what was the return?

## 2. Users

| Role | Who | Main needs |
|---|---|---|
| Owner / manager | Farm owner | Full access, reports, costs, ROI, settings, user management |
| Shepherd / worker | Several daily staff, each with own login | Fast data entry in the barn from a phone: scan tag, weigh, photograph, record birth, treat, move, add cost |
| Veterinarian | External or on-call | Read health history, record treatments and diagnoses |
| Accountant (optional, later) | External | Read cost and sales data, export |

Primary device for daily work is a **mobile phone in the barn**. Desktop is for reports, dashboards and
administration. Every user has a personal login; every record stores who created it.

## 3. Scale

| | Now | 3-year target |
|---|---|---|
| Active animals | ~100 | ~1,000 |
| Users | 2–5 | 5–10 |
| Photos | several per animal | tens of thousands of files |

Design for 5,000 active animals and 10 years of history.

## 4. Phased Delivery

### Phase 1 — Animal Registry, Costs, Reports (MVP)
1. **Animal record** keyed by RFID tag (optional visual tag), with dam and sire.
2. **RFID scan-to-open** — type or scan the tag; the animal page opens instantly.
3. **Weight log** — repeated weighings, growth chart, average daily gain, monthly gain.
4. **Photo gallery** — multiple dated images per animal in object storage.
5. **Entry & exit events** — born here / purchased / transferred in; sold / died / culled / transferred out.
6. **Age display** — computed from birth date in days, months, or years.
7. **Pen / group assignment** with movement history.
8. **Search & list** — by tag, status, sex, age range, pen, breed.
9. **Cost tracking tool** (Section 6) — amount, explanation, cost date, folder, receipt photo.
10. **AI receipt analysis** (Section 10) — photo of a receipt pre-fills the cost form.
11. **Per-animal report screen** (Section 8) — designed, chart-rich summary of one animal.
12. **Dashboard** (Section 9) — herd status, monthly and yearly weight gain, costs, charts.
13. **Users & roles** — owner, worker, vet.

### Phase 2 — Feed Cost Plans, Sales & ROI
14. **Feed cost plans** (Section 7) — recurring daily / weekly / custom-interval feed costs by feed type, scoped to herd or pen; automatic cost entries; herd cost per day.
15. **Cost allocation per animal** — every cost is spread to the animals it covers, giving a running cost-to-date per animal.
16. **Sales** (Section 11) — sale price per animal (per head or per kg), buyer, date; earnings.
17. **ROI** (Section 11) — per animal, per sale batch, per period, and herd-wide; shown on the animal report and dashboard.

### Phase 3 — Health & Breeding
18. **Health records** — vaccinations, treatments, diagnoses, withdrawal periods, vet visits; treatment costs flow into the cost tool automatically.
19. **Scheduled tasks / reminders** — recurring vaccination and deworming plans, due lists.
20. **Breeding** — mating/ram assignment, pregnancy check, expected lambing date, lambing record; lambs created with dam and sire set.
21. **Full pedigree view** — multi-generation tree, inbreeding warning.
22. **Breeding-stock performance** — per ram / per ewe: lambs born, survival, weaning weights, offspring growth, offspring ROI.
23. **AI photo analysis for animals** — captions, body condition hints, visible concerns (advisory only).
24. **Lambing-detector integration** — ingest alarms and snapshots from `surveilance/`.

### Phase 4 — Operations
25. **Feed & medicine inventory** — stock levels, consumption, expiry; links feed plans to stock.
26. **Purchases of animals** — seller contacts, batch purchases.
27. **Reports & exports** — CSV/Excel/PDF; ministry format if required.

### Later
Bluetooth RFID reader and scale pairing, offline queue with sync, wool/shearing, pasture rotation, multi-farm.

## 5. Core Data Model

### 5.1 Animal
| Field | Type | Notes |
|---|---|---|
| id | uuid | internal |
| rfid | string, unique among active | **primary identifier** |
| visual_tag, tag_color | string, nullable | |
| name | string, nullable | |
| sex | enum | ewe, ram, wether |
| breed | FK → Breed | |
| birth_date, birth_date_is_estimated | date, bool | |
| origin | enum | born_here, purchased, transferred_in |
| entry_date | date | |
| dam, sire | FK → Animal, nullable | |
| status | enum | active, sold, dead, culled, transferred_out, lost |
| exit_date, exit_reason | date, text | |
| current_pen | FK → Pen | denormalized |
| purchase_price, purchase_currency | decimal, string | if purchased |
| notes | text | |
| created_by, created_at, updated_at | | audit |

Age is computed from `birth_date`: `< 60 days` → days; `< 24 months` → months; otherwise years + months.
Tag uniqueness is enforced among active animals only; tag replacement is a `TagChange` event and search finds any historical tag.

### 5.2 WeightRecord
animal, weighed_at, weight_kg (1 decimal), method (scale / estimate), recorded_by, note.
Derived per animal: average daily gain (ADG) between weighings, gain per calendar month, gain since entry.
Derived per herd/pen/age class: average weight, total and average gain per month and per year.

### 5.3 AnimalImage
animal, object key, thumbnail key, taken_at, caption, is_primary, ai_analysis JSON, uploaded_by.

### 5.4 Pen and Movement
Pen: name, type (barn, pen, pasture, quarantine, lambing pen), capacity.
Movement: animal, from_pen, to_pen, moved_at, reason, recorded_by.

### 5.5 Event (unified timeline)
One row per happening: birth, entry, weighing, photo, movement, treatment, vaccination, mating, pregnancy check, lambing, tag change, cost allocation, sale, death. Detail tables hold specifics.

### 5.6 Costs
CostFolder, CostEntry, CostAttachment, FeedType, FeedPlan, CostAllocation — Sections 6 and 7.

### 5.7 Sales
Sale, SaleLine — Section 11.

### 5.8 Health / Breeding (Phase 3)
Treatment, Vaccination, HealthPlan, Mating, PregnancyCheck, Lambing.

### 5.9 Users & Settings
User (name, email, password hash, role, active), Breed, Pen, Medicine, Vaccine, FeedType, CostFolder, farm profile, currency, language.

## 6. Cost Tracking Tool

A small, fast expense log. Not a general ledger.

### 6.1 Concepts
- **Folder** — user-defined bucket: *Feed*, *Vet & Medicine*, *Equipment*, *Fuel & Transport*, *Labor*, *Building & Maintenance*, *Animal Purchase*, *Other*. One level of nesting allowed. Owner manages folders.
- **Cost entry** — one expense, manual or generated (by a feed plan, a treatment, or a purchase).

### 6.2 CostEntry
| Field | Notes |
|---|---|
| folder | required |
| amount, currency | default TRY |
| explanation | required free text |
| cost_date | when it happened; defaults to today |
| vendor, quantity, unit | optional |
| source | manual / feed_plan / treatment / purchase — generated entries link back to their source |
| scope | herd / pen / animal set — what this cost covers; drives allocation (Section 7.3). Default: whole herd |
| attachments | receipt photos |
| ai_extracted | raw AI JSON, for audit |
| created_by, created_at, updated_at | `created_at` is distinct from `cost_date` |

### 6.3 Flows
1. **Manual entry** — folder, amount, explanation, date defaults to today. Under 15 seconds on a phone.
2. **Photo-first entry** — receipt photo → AI → pre-filled form → user confirms.
3. **Browse** — by month, by folder, search; totals per folder per month; monthly spend chart.
4. **Export** — CSV of any filtered view.

### 6.4 Permissions
Workers add costs and edit their own for 24 hours. Owner edits/deletes anything and manages folders. Soft delete only.

## 7. Feed Cost Plans and Herd Cost

### 7.1 Goal
Feed is the largest recurring cost. Instead of typing it every day, the owner defines **feed plans**; the
system generates the cost entries on schedule and reports **herd cost per day / week / month**.

### 7.2 FeedType
name (e.g. Hay, Alfalfa, Barley, Concentrate, Silage, Straw, Mineral block), unit (kg, bale, bag), current unit price, price history (price changes dated, so past costs stay correct).

### 7.3 FeedPlan
| Field | Notes |
|---|---|
| name | e.g. "Winter ration — ewes" |
| feed_type | FK |
| quantity per occurrence | e.g. 120 kg |
| unit price | snapshot from FeedType at the time, overridable |
| frequency | **daily**, **weekly** (pick weekdays), or **custom** (every N days) |
| scope | whole herd, one or more pens, or an explicit animal list |
| start_date, end_date | end optional (open-ended) |
| active | pause without deleting |
| notes | |

Multiple plans can run at once (e.g. hay daily for herd + concentrate daily for lambing pen + mineral weekly).

### 7.4 Generation
A daily cron job materializes due plan occurrences into **CostEntry** rows in the *Feed* folder
(`source = feed_plan`). Entries are editable (e.g. one day they fed less) and flagged as adjusted.
Price changes on a FeedType only affect future occurrences.

### 7.5 Herd cost figures
- **Herd feed cost per day** = sum of today's feed entries. Shown on dashboard with 7-day and 30-day averages.
- **Herd cost per day (all folders)** = feed + other entries spread over their period.
- **Cost per animal per day** = scope cost ÷ animals in scope that day. Default equal split; later option to weight by age class.
- **Projected monthly feed cost** from active plans, so the owner can see the effect of a plan change before saving.

### 7.6 CostAllocation
Nightly job writes one allocation row per (cost entry, animal, date) for the animals in scope. This gives every animal a running **cost-to-date**, broken down by folder, which the animal report and ROI use. Allocations are recomputed when an entry or its scope changes.

## 8. Per-Animal Report Screen

A single, designed page that tells the whole story of one animal; printable and shareable as PDF
(useful when selling breeding stock).

### 8.1 Layout
1. **Header card** — primary photo, tag, name, sex, breed, age, status, current pen, days on farm.
2. **Key figures row** — current weight, total gain, ADG (lifetime and last 30 days), cost-to-date, sale price / ROI (if sold) or estimated value (if a market price per kg is set).
3. **Growth chart** — weight over time with: the animal's line, herd or same-age-class average as a comparison band, and markers for events (moves, treatments, lambing). Monthly gain shown as bars beneath.
4. **Monthly gain table** — month, start weight, end weight, gain, ADG.
5. **Cost breakdown** — donut or stacked bar by folder (feed, vet, other, purchase), plus cost per day and cost per kg gained.
6. **Pedigree panel** — dam and sire with photos; offspring list with their current weights (Phase 3 expands to a tree).
7. **Health summary** (Phase 3) — last vaccination, open treatments, withdrawal status.
8. **Breeding summary** (Phase 3) — matings, pregnancies, lambings with litter sizes.
9. **Timeline** — all events, newest first.
10. **Photo strip** — thumbnails by date.

### 8.2 Design notes
Charts follow one visual system (consistent palette, typography, light/dark). Charts must stay readable on a phone. A "share" action produces a PDF or a link-protected read-only page.

## 9. Dashboard

### 9.1 Herd status
- Total active animals; split by sex, by age class (lamb < 6 mo, yearling 6–18 mo, adult), by breed, by pen.
- Movements in the period: births, purchases, sales, deaths, culls.
- Herd count trend line over the last 12 months.
- Attention list: animals with no weighing in 30+ days, weight loss since last weighing, under-target lambs, due tasks (Phase 3).

### 9.2 Weight performance
- **Monthly**: average herd weight gain per animal this month vs. last month; total kg gained; by age class and pen.
- **Yearly**: month-by-month bars for the current year with prior-year overlay; total gain, average ADG, best and worst pens.
- Distribution chart of current weights by age class.

### 9.3 Costs and returns
- Herd feed cost today, this week, this month; projected month from active plans.
- Monthly cost by folder (stacked bars, 12 months).
- Cost per animal per day trend.
- Earnings from sales this month / year; ROI for the period (Phase 2).

### 9.4 Filters and time range
Global period selector (this month, last 30 days, this year, custom) and pen/breed filters apply to all widgets.

## 10. AI Image Analysis

| Use | Input | Output | Phase |
|---|---|---|---|
| Receipt extraction | receipt/invoice photo | amount, currency, date, vendor, line items, suggested folder, confidence | 1 |
| Animal photo analysis | sheep photo | caption, body condition estimate, visible concerns, suggested tags | 3 |

Server-side only; results are suggestions the user confirms; model and prompt version stored with each result. Provider: Anthropic Claude vision by default, exact model confirmed at implementation; Cloudflare Workers AI as fallback.

## 11. Sales, Earnings and ROI

### 11.1 Sale
| Field | Notes |
|---|---|
| sale_date | |
| buyer | name, contact (optional) |
| pricing | per head or per kg |
| lines | one per animal: animal, live weight at sale (optional), price, currency |
| total, notes, attachments (contract / receipt photo) | |

Saving a sale sets each animal's status to `sold`, exit_date, and sale price, and writes a `sale` event.

### 11.2 Per-animal economics
- **Total cost** = purchase price (if purchased) + allocated costs to date (feed, vet, other). For born-here animals, optionally include a share of the dam's cost during gestation (configurable, off by default).
- **Earnings** = sale price (+ other revenue linked to the animal later, e.g. wool).
- **Profit** = earnings − total cost.
- **ROI %** = profit ÷ total cost × 100.
- **Cost per kg gained** and **price per kg** shown alongside.
- For active animals, **estimated value** = current weight × market price per kg (owner-set, dated) gives an **unrealized ROI**.

### 11.3 Aggregates
- ROI per sale batch, per month, per year, per pen, per breed, per sire/dam (Phase 3).
- Herd ROI for a period = total earnings ÷ total costs in that period.
- Dashboard widget and a Sales report with a sortable table and charts.

## 12. Non-Functional Requirements

- Mobile-first, large touch targets, high contrast.
- RFID input via keyboard-wedge Bluetooth reader (types tag + Enter); no special integration for v1.
- Phase 1 requires connectivity but never loses form data on a failed submit; offline queue later.
- Turkish primary UI, English second; all strings translatable.
- Metric units; TRY default currency; ISO dates in storage.
- Audit who/when on everything; soft delete.
- Daily automated DB export to R2 and object versioning; restore tested before go-live.
- Tag lookup < 300 ms; dashboards use precomputed daily aggregates so they load fast at 1,000+ animals.
- Login required, roles, HTTPS, authenticated image URLs.
- Full data export (CSV + images) at any time.

## 13. Decisions Made

| Topic | Decision |
|---|---|
| Herd size | ~100 now, ~1,000 in 3 years |
| Identification | RFID electronic ear tags, optional visual tag |
| Operation type | Breeding stock; no milk module |
| Users | Several, each with own login and role |
| Hosting | Cloudflare (Workers, D1, R2, Queues, Cron) |
| Framework / UI | Next.js + shadcn/ui |
| Cost tracking | Small tool: amount, explanation, date, folder, receipt photo, AI extraction |
| Feed costs | Recurring plans (daily / weekly / custom), by feed type, scoped to herd or pen, auto-generated entries, herd cost per day |
| Reports | Per-animal designed report with charts; dashboard with herd status, monthly and yearly weight gain, costs |
| Sales & ROI | Sale price per animal → earnings; per-animal and herd ROI from allocated costs |

## 14. Still Open

1. **Breeds** on the farm (seed list).
2. **Language** — Turkish-only for v1, or bilingual from the start?
3. **Government reporting** — ministry animal registry (TÜRKVET) files needed?
4. **Receipt language** — mostly Turkish?
5. **Cost folders** — accept the proposed seed list in 6.1?
6. **Feed types and current prices** — initial list to seed.
7. **Cost allocation rule** — equal split per animal is the default; want age-class weighting (e.g. lamb = 0.5 adult) from the start?
8. **Market price per kg** — do you want to maintain it for unrealized value / ROI on live animals?
9. **Domain name**.

## 15. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Framework | Next.js (App Router, TypeScript) on Cloudflare Workers | OpenNext Cloudflare adapter or vinext, chosen at scaffold |
| UI | shadcn/ui + Tailwind, installable PWA | charts via Recharts with one shared chart theme |
| Database | Cloudflare D1 (SQLite) | |
| ORM | Drizzle ORM | migrations in repo |
| Images | Cloudflare R2 | originals + thumbnails, authenticated routes |
| Auth | Email/password sessions, roles in DB | e.g. better-auth |
| AI | Anthropic API from a server route; results stored in D1 | Workers AI fallback |
| Background | Cloudflare Queues | AI analysis, thumbnails |
| Scheduled | Cloudflare Cron Triggers | feed plan generation, cost allocation, daily aggregates, backups |
| Dev / deploy | Wrangler, local D1 and R2 | preview deploy per branch |

### Repository layout (planned)
```
erp/
  SCOPE.md
  app/            Next.js routes
  components/     shadcn/ui + farm components + charts
  db/             drizzle schema + migrations
  lib/            domain logic (age, growth, costs, allocation, roi, ai, auth)
  workers/        queue consumers, cron handlers
  wrangler.toml
```
