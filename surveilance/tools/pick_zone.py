"""Draw a polygon on a camera frame and print it for config.yaml.

  python tools/pick_zone.py "rtsp://..."      or    python tools/pick_zone.py frame.jpg
Left click adds a point, right click removes the last one, Enter prints and quits, Esc quits.
"""
import sys

import cv2

pts = []


def on_mouse(ev, x, y, flags, param):
    if ev == cv2.EVENT_LBUTTONDOWN:
        pts.append((x, y))
    elif ev == cv2.EVENT_RBUTTONDOWN and pts:
        pts.pop()


if __name__ == "__main__":
    src = sys.argv[1]
    cap = cv2.VideoCapture(src)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit("cannot read a frame from " + src)
    cv2.namedWindow("pick zone")
    cv2.setMouseCallback("pick zone", on_mouse)
    while True:
        img = frame.copy()
        for i, p in enumerate(pts):
            cv2.circle(img, p, 4, (0, 0, 255), -1)
            if i:
                cv2.line(img, pts[i - 1], p, (0, 255, 0), 2)
        if len(pts) > 2:
            cv2.line(img, pts[-1], pts[0], (0, 255, 0), 1)
        cv2.putText(img, "L-click add, R-click undo, Enter done, Esc quit", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("pick zone", img)
        k = cv2.waitKey(30) & 0xFF
        if k in (13, 10):
            print("polygon:", [[int(x), int(y)] for x, y in pts])
            break
        if k == 27:
            break
    cv2.destroyAllWindows()
