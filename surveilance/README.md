# Sheep Heaven – farm camera surveillance

Camera monitoring for the sheep farm. See `SCOPE.md` for the full scope.

| Monitor | What it does | Alarm |
|---------|--------------|-------|
| `lambing` | Tracks every ewe, scores restlessness / isolation / side-lying, confirms labour stage with the Jev vision model, pen-wide safety-net check | pre-alarm on early labour, urgent repeating alarm on active labour or lamb born, problem alarm on long labour |
| `feeding` | Sheep count and visits per trough zone, activity index, feed level by vision model every 20 min | low/empty feed, water problem, no trough visits for hours |
| `intruder` | People, vehicles, dogs outside working hours or inside restricted zones, vision model describes the action | warning or urgent with photo |

## Setup

```bash
cd surveilance
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # fill TYPESAFE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

Telegram: create a bot with `@BotFather`, add it to a group with the farmer(s), send a message,
then read the chat id from `https://api.telegram.org/bot<TOKEN>/getUpdates`.
In the group, `/ack` silences the current urgent alarms, `/status` lists them.

Edit `config.yaml`: camera RTSP urls, which monitors run on which camera, trough polygons
(draw them with `python tools/pick_zone.py "rtsp://..."`), working hours.

## Run

```bash
.venv/bin/python -m farmwatch.main --config config.yaml --dashboard   # dashboard on http://localhost:8080
.venv/bin/python -m farmwatch.main --dry-run                           # no cloud calls, no Telegram
```

Replay a recorded video through one camera's monitors (time runs 10x faster for the behaviour clocks):

```bash
.venv/bin/python -m farmwatch.main --camera lambing_pen_1 --source footage/night1.mp4 --speed 10 --dry-run
```

Test the vision model on a single photo:

```bash
.venv/bin/python tools/ask_jev.py photo.jpg --mode lambing   # or pen / feed / person / dog
```

Docker on the edge box: `docker compose up -d --build`.

## Layout

```
farmwatch/
  camera.py      RTSP / file frames with reconnect, 2 fps sampling
  detector.py    YOLO11 + ByteTrack, classes sheep/person/dog/vehicles
  vision.py      typesafe.ai Jev client, structured questions, daily budget
  alarm.py       Telegram with cooldowns, repeat, /ack
  storage.py     SQLite events + observations + snapshots
  pipeline.py    one thread per camera
  dashboard.py   FastAPI page: events with photos, live values
  monitors/      lambing.py, feeding.py, intruder.py
tools/           ask_jev.py, pick_zone.py
data/            events.sqlite, snapshots/ (created at runtime)
```

## Tuning the lambing detector

Run on recorded footage with `--dry-run --log-level DEBUG` and watch `max_suspect_score` in the
dashboard. Too many suspects: raise `suspect_score` or `min_transitions`. Missed ewes: lower them, or
shorten `safety_net_minutes`. Night footage needs IR cameras; validate YOLO detections first, and
if sheep are missed switch to `yolo11s.pt` or fine-tune on a few hundred labelled frames.
