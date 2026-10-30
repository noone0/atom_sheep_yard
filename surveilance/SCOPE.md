# Sheep Farm Camera Surveillance – Scope Document

Status: Draft v0.1 – 2026-10-30
Folder: `surveilance/`

## 1. Purpose

Build a camera-based monitoring system for the sheep farm that watches the animals
24/7 and alerts the farmer on their phone when something needs attention.

Three monitoring goals, delivered in phases:

| Phase | Goal | Priority |
|-------|------|----------|
| 1 | Detect the **start of lambing (birth)** and alarm immediately | Highest – build first |
| 2 | Feeding and activity: are the sheep eating enough, is feed available | Medium |
| 3 | Unusual people, vehicles, predators and unusual actions | Medium |

This document covers all three for context, and defines Phase 1 in detail.

## 2. Phase 1 – Lambing onset detection

### 2.1 What we detect

"Start of lambing" is a sequence of visible behaviours in the ewe. The system
looks for them in this order and escalates:

| Stage | Visible signs (what the camera can see) | Typical timing |
|-------|------------------------------------------|----------------|
| Early labour | Restless: lies down and stands up repeatedly, paws the bedding, walks away from the flock and stays apart, turns head to look at her flank, stops eating | 2–12 hours before birth |
| Active labour | Lies flat on her side, neck stretched, visible straining / pushing, water bag or fluid at the rear, hooves or nose of the lamb appearing | 30–60 minutes before birth |
| Lamb delivered | A small wet lamb on the ground next to the ewe, ewe licking it | Birth |
| Problem | Active labour continues for more than ~60 minutes with no lamb, or ewe lying on side without movement for a long time | Needs vet / farmer intervention |

### 2.2 Alarm behaviour

- **Pre-alarm (info):** early labour signs confirmed → one message "Ewe in pen 1 looks like early labour" with a photo. Lets the farmer prepare.
- **Alarm (urgent):** active labour or lamb delivered confirmed → repeated urgent message with photo. Sent again every N minutes until the farmer acknowledges or the stage changes.
- **Problem alarm:** active labour with no lamb after the configured limit → "Possible dystocia, check ewe now".
- **Per-ewe cooldown** so the same ewe in the same stage does not spam, but a stage change always sends.
- Delivery channel: Telegram bot (phase 1). WhatsApp or SMS later if needed.

### 2.3 Detection approach – hybrid

Sending every frame to a cloud vision model every 3–5 seconds is too expensive
(about 17,000 images per camera per day) and a single frame cannot see behaviour
over time. Local YOLO alone cannot understand "labour". So:

1. **Local, always on (edge box):** YOLO detects and tracks each sheep in the
   lambing pen at ~2 frames per second. From the tracks we compute per-ewe
   behaviour signals: posture (standing / lying / lying flat on side), number of
   lie-stand transitions in the last 15 minutes, isolation from the group, and
   how long she has been lying on her side.
2. **Suspect rule:** a weighted score of those signals. Above a threshold the ewe
   becomes a *suspect*.
3. **Cloud confirmation (Jev vision model via typesafe.ai):** for a suspect ewe
   we send a cropped frame plus the full frame every ~45 seconds and ask
   structured questions: labour stage (none / early / active / lamb delivered),
   lamb visible yes/no, water bag or hooves visible yes/no. Two consecutive
   positive answers trigger the alarm. This keeps cloud calls to tens or a few
   hundred per day instead of thousands.
4. **Safety net:** even with no suspect, the whole pen image is checked by the
   vision model every 10 minutes, so a missed track cannot silently miss a birth.
5. **Night:** cameras must have infrared. Most births happen at night, so the
   whole pipeline is tested on IR footage.

### 2.4 Components

| Component | Technology | Runs where |
|-----------|-----------|------------|
| Cameras | PoE IP cameras, RTSP, IR night vision, wide lens for pens | Barn |
| Frame ingest | OpenCV reading RTSP, reconnect on drop, 2 fps sampling | Edge box |
| Detection + tracking | Ultralytics YOLO11 (COCO class "sheep") + ByteTrack | Edge box |
| Behaviour engine | Python rules over track history (posture, transitions, isolation) | Edge box |
| Vision confirmation | Jev (`jev-latest`) via typesafe.ai System One API, Choice and Noul questions | Cloud |
| Alarm | Telegram bot, photo + text, cooldown, repeat until acknowledged | Cloud → phone |
| Storage | SQLite event log + JPEG snapshots per event | Edge box |
| Config | `config.yaml` (cameras, thresholds) + `.env` (API keys) | Edge box |
| Tools | replay a recorded video file through the pipeline; send one image to Jev and print answers | Dev laptop |

Edge box: a small PC or NVIDIA Jetson Orin Nano in the barn or farm office, wired
to the cameras, with internet for the cloud calls and Telegram.

### 2.5 Out of scope for Phase 1

- Individual sheep identification (ear tags, RFID). Alarms say "ewe in pen 1", not the ewe's name.
- Due-date tracking or integration with breeding records.
- Web dashboard (comes with Phase 2).
- Detecting health problems other than lambing.
- Training a custom YOLO model. We start with the stock COCO "sheep" class and only fine-tune if detection on the real footage is poor.

### 2.6 Success criteria

- Alarm within 5 minutes of active labour starting, on at least 90% of births in the test period.
- Fewer than 2 false urgent alarms per pen per night after tuning.
- Cloud vision usage under a configurable daily budget per camera.
- System recovers automatically from camera disconnects and power cycles.

### 2.7 Risks and open questions

- The Jev image feature is marked "Dreamer-ready" (not production) and image token cost is not yet documented. We measure real usage on the first day and keep the vision client behind an interface so the model can be swapped.
- Stock YOLO may confuse lying sheep with bedding or miss sheep under IR. Needs validation on real footage; fallback is fine-tuning with a few hundred labelled frames.
- Pen layout: a crowded pen makes isolation and posture harder. Lambing pens with few ewes per camera give the best results.
- Open: number of cameras and pens, Telegram vs WhatsApp, who receives alarms, how far the edge box is from the cameras.

## 3. Phase 2 – Feeding and activity (summary)

- Polygon zone per feed trough; count sheep in zone per minute and time per visit from the same tracks.
- Flag sheep that do not visit a trough for a configurable number of hours.
- Every 15–30 minutes send one trough image to the vision model with a Score question "feed level 0–10"; alert when low.
- Daily activity summary and a simple web dashboard reading from the event database.

## 4. Phase 3 – Unusual people and actions (summary)

- YOLO classes person, car, truck, dog on gate, yard and perimeter cameras.
- Rules: outside working hours, inside restricted zones, unknown vehicle, dog near sheep.
- On trigger, vision model answers "what is the person doing", "carrying an animal or tools", "is a dog attacking sheep", then alarm with photo.
- Optional: known-person allowlist by schedule rather than face recognition.

## 5. Delivery plan

1. Scope sign-off (this document).
2. Phase 1 code: ingest, detector, behaviour engine, Jev client, Telegram alarm, replay tool.
3. Test on recorded lambing footage; tune thresholds.
4. Install edge box and cameras in one lambing pen; run through one lambing season window.
5. Review results, then Phase 2 and Phase 3.
