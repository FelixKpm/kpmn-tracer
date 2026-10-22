"""Person segmentation (MediaPipe) behind a small interface so it can be swapped/faked in tests."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

log = logging.getLogger(__name__)

_REPO_MODELS = Path(__file__).resolve().parents[2] / "vendor" / "models"

MODEL_FILES = {
    "pose": "pose_landmarker_full.task",
    "multiclass": "selfie_multiclass_256x256.tflite",
    "deeplab": "deeplab_v3.tflite",
}
DEFAULT_MODEL = "multiclass"


class PersonSegmenter(Protocol):
    def segment(self, bgr: np.ndarray) -> np.ndarray:
        """Return float32 person probability in [0, 1] with the image's height/width."""
        ...


class ModelNotFoundError(FileNotFoundError):
    pass


def model_path(name: str) -> Path:
    fname = MODEL_FILES[name]
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "models" / fname)
    candidates.append(_REPO_MODELS / fname)
    for c in candidates:
        if c.is_file():
            return c
    raise ModelNotFoundError(f"MediaPipe model {fname} not found - run 'python tools/fetch_models.py'")


class MediaPipeSegmenter:
    """Person mask from one of the MediaPipe models.

    * ``multiclass`` - selfie multiclass (hair/body/face/clothes/...): 1 - background
    * ``deeplab``    - DeepLab v3 (Pascal VOC), class 15 = person
    * ``pose``       - pose landmarker segmentation output (single full-body person)
    """

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self.model = model
        self._mp = mp
        self._lock = threading.Lock()
        opts = BaseOptions(model_asset_path=str(model_path(model)))
        try:
            if model == "pose":
                self._task = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                    base_options=opts, running_mode=vision.RunningMode.IMAGE, num_poses=2,
                    output_segmentation_masks=True, min_pose_detection_confidence=0.3))
            else:
                self._task = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                    base_options=opts, running_mode=vision.RunningMode.IMAGE,
                    output_confidence_masks=True, output_category_mask=False))
        except OSError as exc:  # Linux: MediaPipe's native library needs the system's OpenGL ES/EGL
            from kpmn_tracer.i18n import tr

            raise RuntimeError(
                tr("Personen-Maske nicht verfügbar – eine Systembibliothek fehlt ({exc}). "
                   "Ubuntu/Debian: sudo apt install libgles2 libegl1", exc=exc)) from exc

    def segment(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        with self._lock:
            if self.model == "pose":
                res = self._task.detect(img)
                masks = [m.numpy_view() for m in (res.segmentation_masks or [])]
                prob = np.max(np.stack(masks), axis=0) if masks else np.zeros((h, w), np.float32)
            else:
                res = self._task.segment(img)
                cm = res.confidence_masks
                if self.model == "multiclass":
                    prob = 1.0 - cm[0].numpy_view()  # category 0 = background
                else:
                    prob = cm[15].numpy_view()  # Pascal VOC "person"
        prob = np.asarray(prob, np.float32).squeeze()
        if prob.shape != (h, w):
            prob = cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)
        return np.clip(prob, 0.0, 1.0)

    def close(self) -> None:
        self._task.close()
