"""GUI smoke tests (offscreen Qt platform)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kpmn_tracer.session import ClipSession  # noqa: E402
from kpmn_tracer.trace.model import AnchorKind  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app: QApplication, tripod_clip: tuple[Path, dict], tmp_path: Path):
    from kpmn_tracer.gui.main_window import MainWindow

    w = MainWindow()
    sess = ClipSession.open(tripod_clip[0], cache_root=tmp_path / "cache")
    sess.project.shots.clear()
    sess.project.ball_start_hint = None
    w.set_session(sess)
    w.dirty = False
    yield w
    w.dirty = False
    w.session = None  # shared session fixtures stay open
    w.close()
    Path(str(tripod_clip[0]) + ".kpmntrace.json").unlink(missing_ok=True)


def wait_until(app: QApplication, cond, timeout: float = 60) -> None:
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.01)
        if time.time() - t0 > timeout:
            raise TimeoutError


def test_manual_tracer_workflow(window, app: QApplication, tripod_clip, tmp_path: Path) -> None:
    w = window
    truth = tripod_clip[1]
    w.goto(15)
    w.add_shot()
    shot = w.current_shot()
    assert shot is not None and shot.impact_frame == 15
    start = truth["frames"][15]["balls"][0]["frame"]
    w.on_view_click(*start)  # tool switched to "start" by add_shot
    assert w.tool == "apex"
    w.on_view_click(330, 120)
    assert w.tool == "land"
    w.on_view_click(350, 160)
    w.goto(80)
    w.set_land_frame()
    assert shot.is_complete() and shot.land_frame == 80
    assert [a.kind for a in shot.anchors] == [AnchorKind.START, AnchorKind.APEX, AnchorKind.LAND]
    assert np.allclose((shot.anchors[0].x, shot.anchors[0].y), start)

    # the preview shows the tracer
    w.goto(60)
    assert w._overlay_buf is not None and w._overlay_buf[..., 3].max() == 255

    # drag the apex handle, undo restores it
    apex_before = (shot.anchors[1].x, shot.anchors[1].y)
    w.on_handle_moved("a1", 300, 100)
    w._end_drag()
    assert w.current_shot().anchors[1].x == pytest.approx(300)
    w.undo()
    assert (w.current_shot().anchors[1].x, w.current_shot().anchors[1].y) == apex_before

    # extra point + delete
    w.set_tool("point")
    w.on_view_click(340, 140)
    assert len(w.current_shot().anchors) == 4
    w.view.selected = "a2"
    w.delete_selected()
    assert len(w.current_shot().anchors) == 3

    # offset keyframe moves the tracer in that frame
    w.set_tool("offset")
    w.goto(50)
    w.on_view_click(100, 100)
    assert len(w.current_shot().offsets) == 3  # correction + two automatic zero keys

    # style change triggers re-render; save project
    w.style_panel.color.set_color("#00ff00")
    w.style_panel._set("color", "#00ff00")
    assert w.project.style.color == "#00ff00"
    assert w.save()
    assert Path(w.project.source + ".kpmntrace.json").exists()


def test_export_runs_in_background(window, app: QApplication, tmp_path: Path) -> None:
    from kpmn_tracer.io.export import ExportSettings

    w = window
    w.goto(15)
    w.add_shot()
    for xy in ((320, 300), (330, 120), (350, 160)):
        w.on_view_click(*xy)
    out = tmp_path / "gui_export.mov"
    w.run_export(ExportSettings("prores", out))
    wait_until(app, lambda: not w.tasks.busy() and out.exists(), 120)
    from kpmn_tracer.io.decode import count_frames

    assert count_frames(out) == w.project.frame_count


def test_navigation_and_playback(window, app: QApplication) -> None:
    w = window
    w.goto(10_000)
    assert w.frame == w.project.frame_count - 1
    w.step(-5)
    assert w.frame == w.project.frame_count - 6
    w.goto(0)
    w.toggle_play()
    wait_until(app, lambda: w.frame >= 3, 10)
    w.toggle_play()
    assert not w.play_timer.isActive()


def test_camera_tracking_and_local_corrections(window, app: QApplication) -> None:
    w = window
    w.goto(15)
    w.add_shot()
    for xy in ((320, 300), (330, 120), (350, 160)):
        w.on_view_click(*xy)
    w.track_camera(force=True)
    wait_until(app, lambda: not w.tasks.busy() and w.current_shot().camera.analyzed, 60)
    shot = w.current_shot()
    assert shot.camera.mode == "tracked"
    assert "getrackt" in w.shot_panel.cam_status.text()
    w.set_tool("offset")
    w.goto(50)
    w.on_view_click(200, 100)
    frames = [o.frame for o in shot.offsets]
    assert len(frames) == 3 and frames[0] < 50 < frames[2]
    assert np.allclose(shot.offset_at(frames[0] - 5), 0) and np.allclose(shot.offset_at(frames[2] + 5), 0)
    # head is where we clicked (proxy == source here)
    u = shot.head_u(50, w.project.fps)
    head = shot.to_frame(shot.path().evaluate(u), 50)[0]
    assert np.allclose(head, (200, 100), atol=1e-6)


def test_occlusion_preview(app: QApplication, person_clip, tmp_path: Path) -> None:
    from kpmn_tracer.gui.main_window import MainWindow
    from kpmn_tracer.segmentation.mask_cache import MaskTrack
    from kpmn_tracer.segmentation.provider import mask_file, settings

    clip, _truth, masks = person_clip
    sess = ClipSession.open(clip, cache_root=tmp_path / "c")
    sess.project.style.glow_strength = 0
    MaskTrack(80, (640, 360), 1, {i: m for i, m in enumerate(masks)}).save(mask_file(sess, *settings(sess)))
    w = MainWindow()
    w.set_session(sess)
    w.goto(20)
    w.add_shot()
    for xy in ((100, 330), (420, 40), (600, 200)):
        w.on_view_click(*xy)
    w.goto(60)
    visible_before = int(w._overlay_buf[..., 3][masks[60] > 0].max())
    w.shot_panel.occlude.setChecked(True)  # -> on_params_changed -> masks already cached
    app.processEvents()
    assert w.current_shot().occlude
    import cv2

    inner = cv2.erode(masks[60], np.ones((7, 7), np.uint8)) > 0
    assert visible_before == 255
    assert w._overlay_buf[..., 3][inner].max() <= 3
    w.dirty = False
    w.session = None  # shared session fixtures stay open
    w.close()


def test_impact_detection_in_gui(app: QApplication, range_session_gui) -> None:
    from kpmn_tracer.gui.main_window import MainWindow

    sess, truth = range_session_gui
    w = MainWindow()
    w.set_session(sess)
    ball = truth["frames"][0]["balls"][0]["frame"]
    sess.project.ball_start_hint = tuple(ball)
    w.goto(0)
    w.detect_impacts()
    wait_until(app, lambda: not w.tasks.busy() and w.candidates(), 120)
    assert sum(c.confidence >= 0.5 for c in w.candidates()) == 3
    assert sum(m.shape == "triangle" for m in w.timeline.markers) >= 3
    w.adopt_all_candidates()
    assert [s.impact_frame for s in w.project.shots] == truth["impact_frames"]
    for s in w.project.shots:
        a = s.anchor(AnchorKind.START)
        assert a is not None and abs(a.x - ball[0]) < 1.5 and abs(a.y - ball[1]) < 1.5
    w.dirty = False
    w.session = None  # shared session fixtures stay open
    w.close()


def test_auto_track_and_simplify_in_gui(app: QApplication, range_session_gui) -> None:
    from kpmn_tracer.gui.main_window import MainWindow

    sess, truth = range_session_gui
    sess.project.shots.clear()
    sess.project.settings["use_person_mask"] = False
    w = MainWindow()
    w.set_session(sess)
    imp = truth["impact_frames"][0]
    w.goto(imp)
    w.add_shot()
    w.on_view_click(*truth["frames"][imp]["balls"][0]["frame"])
    w.auto_track_shot()
    wait_until(app, lambda: not w.tasks.busy() and w.current_shot().source == "auto", 120)
    shot = w.current_shot()
    assert shot.confidence >= 0.5 and shot.uses_anchor_times()
    assert len(w._handles()) <= 4  # dense auto anchors hidden, main ones shown
    land = shot.flight_frames(sess.project.fps)
    w.simplify_shot()
    s2 = w.current_shot()
    assert [a.kind for a in s2.anchors] == [AnchorKind.START, AnchorKind.APEX, AnchorKind.LAND]
    assert abs(s2.flight_frames(sess.project.fps) - land) < 1e-6
    w.undo()
    assert w.current_shot().uses_anchor_times()
    w.dirty = False
    w.session = None  # shared session fixtures stay open
    w.close()


def test_presets_text_confirm_and_batch_window(app: QApplication, range_session_gui, isolated_presets,
                                               tmp_path: Path) -> None:
    from kpmn_tracer.gui.main_window import MainWindow
    from kpmn_tracer.project.presets import PresetStore

    sess, truth = range_session_gui
    sess.project.shots.clear()
    sess.project.ball_start_hint = None
    w = MainWindow()
    w.set_session(sess)
    imp = truth["impact_frames"][0]
    w.goto(imp)
    w.add_shot()
    ball = truth["frames"][imp]["balls"][0]["frame"]
    for xy in (ball, (330, 60), (360, 120)):
        w.on_view_click(*xy)
    # style preset save / load
    w.project.style.color = "#00ff00"
    w.store.save_style("Mein Grün", w.project.style)
    w.project.style.color = "#ff0000"
    w.apply_style_preset("Mein Grün")
    assert w.project.style.color == "#00ff00"
    # text label is rendered into the overlay
    w.text_panel.text.setText("PW · 95 m")
    w.on_text_changed()
    assert w.current_shot().text == "PW · 95 m"
    w.goto(imp + 40)
    with_text = int((w._overlay_buf[..., 3] > 0).sum())
    w.current_shot().text = ""
    w._preview_shots = None
    w.refresh()
    assert with_text > int((w._overlay_buf[..., 3] > 0).sum()) + 500
    # confirm toggles
    w.toggle_confirm()
    assert w.current_shot().confirmed
    # saving remembers the tripod position; it is used in another clip only on request (D36)
    assert w.save()
    pre = PresetStore().load_position()
    assert pre is not None and abs(pre.start[0] * 640 - ball[0]) < 1
    w.project.ball_start_hint = None
    w.goto(truth["impact_frames"][1])
    w.add_shot()
    s2 = w.current_shot()
    assert s2.anchor(AnchorKind.START) is None and s2.anchor(AnchorKind.LAND) is None
    w.apply_last_position()
    assert abs(s2.anchor(AnchorKind.START).x - ball[0]) < 1 and s2.anchor(AnchorKind.LAND) is None
    # batch window shows the review list of a folder
    w.open_batch()
    bw = w.batch_window
    from kpmn_tracer.batch import ClipResult, ShotReview

    bw.show_results([ClipResult(sess.project.source, "x", [
        ShotReview(sess.project.source, w.project.shots[0].id, 0, imp, 1.0, 0.9, False, None)])])
    assert len(bw.items()) == 1
    w.dirty = False
    w.session = None  # shared session fixtures stay open
    bw.close()
    w.close()
    Path(sess.project.source + ".kpmntrace.json").unlink(missing_ok=True)


def test_still_image_and_project_reset(window, app: QApplication, tmp_path: Path, monkeypatch) -> None:
    """'Frame als Bild speichern' writes the full-resolution frame; 'Projekt zurücksetzen' forgets the clip state."""
    import cv2
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    w = window
    w.goto(15)
    w.add_shot()
    for xy in ((320, 300), (330, 120), (350, 160)):
        w.on_view_click(*xy)
    w.goto(40)
    out = tmp_path / "post.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "PNG (*.png)"))
    w.save_still_dialog()
    wait_until(app, lambda: not w.tasks.busy() and out.exists(), 60)
    img = cv2.imread(str(out))
    assert (img.shape[1], img.shape[0]) == (w.project.width, w.project.height)

    w.project.settings["impact_candidates"] = [{"frame": 3, "time": 0.1, "confidence": 0.2, "sources": ["audio"]}]
    w.project.style.color = "#123456"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    w.reset_project()
    p = w.project
    assert not p.shots and p.ball_start_hint is None and not p.settings.get("impact_candidates")
    assert p.style.color == "#123456"  # look is kept
    w.undo()
    assert len(w.project.shots) == 1
