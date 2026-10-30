"""Frame source with reconnect and rate limiting (RTSP stream or video file)."""
import logging
import os
import time
from typing import Iterator, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


class Camera:
    def __init__(self, name: str, source: str, sample_fps: float = 2.0, speed: float = 1.0):
        self.name = name
        self.source = source
        self.sample_fps = sample_fps
        self.speed = speed  # file replay only: >1 compresses time for the behaviour engine
        self.is_file = os.path.exists(source)
        self._cap: Optional[cv2.VideoCapture] = None
        self._src_fps = 25.0

    def _open(self) -> bool:
        if self._cap is not None:
            self._cap.release()
        if self.source.startswith("rtsp://"):
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            log.warning("[%s] cannot open %s", self.name, self.source)
            return False
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._src_fps = fps if fps and fps > 0 else 25.0
        log.info("[%s] opened %s (%.1f fps)", self.name, self.source, self._src_fps)
        return True

    def frames(self) -> Iterator[Tuple[float, np.ndarray]]:
        """Yield (timestamp, frame) at roughly sample_fps.

        For files the timestamp comes from the frame index (times `speed`) so a
        replay behaves like real time for the behaviour engines. For streams it
        is wall-clock time.
        """
        backoff = 1.0
        t0 = time.time()
        while True:
            if self._cap is None or not self._cap.isOpened():
                if not self._open():
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                backoff = 1.0

            if self.is_file:
                step = max(1, int(round(self._src_fps / self.sample_fps)))
                idx = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
                ok, frame = self._cap.read()
                if not ok:
                    log.info("[%s] end of file", self.name)
                    return
                if idx % step != 0:
                    continue
                yield t0 + (idx / self._src_fps) * self.speed, frame
            else:
                # Streams: keep grabbing so the decoder buffer never goes stale,
                # decode only when a sample is due.
                t_next = time.time() + 1.0 / self.sample_fps
                ok = True
                while time.time() < t_next and ok:
                    ok = self._cap.grab()
                if not ok:
                    log.warning("[%s] stream lost, reconnecting", self.name)
                    self._cap.release()
                    self._cap = None
                    continue
                ok, frame = self._cap.retrieve()
                if not ok:
                    continue
                yield time.time(), frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
