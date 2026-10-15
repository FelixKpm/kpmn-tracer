"""Download the MediaPipe models into ``vendor/models`` (bundled by the PyInstaller build).

Usage::

    python tools/fetch_models.py
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

log = logging.getLogger("fetch_models")

BASE = "https://storage.googleapis.com/mediapipe-models"
MODELS = {
    # full-body person segmentation (pose model with segmentation output)
    "pose_landmarker_full.task": f"{BASE}/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    # general segmentation incl. "person" class (fallback / comparison)
    "selfie_multiclass_256x256.tflite": f"{BASE}/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
    "deeplab_v3.tflite": f"{BASE}/image_segmenter/deeplab_v3/float32/1/deeplab_v3.tflite",
}
TARGET = Path(__file__).resolve().parent.parent / "vendor" / "models"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, url in MODELS.items():
        dst = TARGET / name
        if dst.exists() and dst.stat().st_size > 0:
            log.info("%s already present", name)
            continue
        log.info("Downloading %s ...", name)
        tmp = dst.with_suffix(dst.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URL
        tmp.replace(dst)
    log.info("Models in %s", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
