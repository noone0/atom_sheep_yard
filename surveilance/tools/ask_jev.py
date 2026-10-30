"""Send one image to the Jev vision model and print the answers.

  python tools/ask_jev.py photo.jpg                 # lambing questions
  python tools/ask_jev.py photo.jpg --mode feed     # feed level questions
  python tools/ask_jev.py photo.jpg --mode person   # intruder questions
"""
import argparse
import json
import os
import sys

import cv2
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from farmwatch.vision import VisionClient  # noqa: E402
from farmwatch.monitors import feeding, intruder, lambing  # noqa: E402

MODES = {
    "lambing": ({"ewe": None, "pen": None},
                {"stage": lambing.STAGE_QUESTION, "lamb_visible": lambing.LAMB_QUESTION,
                 "birth_signs": lambing.SIGNS_QUESTION}),
    "pen": ({"pen": None}, {"stage": lambing.PEN_QUESTION, "lamb_visible": lambing.LAMB_QUESTION}),
    "feed": ({"trough": None}, {"level": feeding.FEED_QUESTION, "water_problem": feeding.WATER_QUESTION}),
    "person": ({"subject": None, "scene": None},
               {"activity": intruder.PERSON_ACTIVITY, "threat": intruder.PERSON_THREAT}),
    "dog": ({"scene": None}, {"attack": intruder.DOG_ATTACK}),
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--mode", choices=sorted(MODES), default="lambing")
    a = ap.parse_args()
    load_dotenv()
    img = cv2.imread(a.image)
    if img is None:
        sys.exit("cannot read " + a.image)
    images, questions = MODES[a.mode]
    vc = VisionClient(os.environ.get("TYPESAFE_API_KEY", ""))
    res = vc.ask({k: img for k in images}, questions, state={"source": "manual test"}, urgent=True)
    print(json.dumps({"error": res.error, "answers": res.answers, "input_tokens": res.input_tokens}, indent=2))
