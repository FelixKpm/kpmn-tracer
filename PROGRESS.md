# Fortschritt

| Phase | Status |
|---|---|
| 1 – Fundament: Import, Vorschau, manueller Tracer, Export | ✅ fertig |
| 2 – Handheld: Kamerabewegung kompensieren | ✅ fertig |
| 3 – Personen-Maske | ⏳ offen |
| 4 – Automatische Impact-Erkennung | ⏳ offen |
| 5 – Automatisches Ball-Tracking | ⏳ offen |
| 6 – Optional: ML-Ballerkennung | ⏳ offen |
| 7 – Workflow & Komfort | ⏳ offen |
| 8 – Packaging & Doku | ⏳ offen |

## Phase 1 – erledigt
- Projekt-Setup: venv, `requirements*.txt`, `pyproject.toml` (pytest), zentrales Logging.
- FFmpeg/ffprobe-Beschaffung (`tools/fetch_ffmpeg.py`), Locator mit Fallbacks.
- Import: ffprobe-Analyse (Auflösung, Rotation, fps, VFR-Erkennung über Paket-Zeitstempel, Farbraum,
  Bit-Tiefe, HLG/PQ/Dolby Vision, Audio).
- Proxy (SDR, rotiert, CFR, MJPEG) + frame-genauer `FrameReader` mit LRU-Cache.
- Kurvenmodell (Hermite durch Anker, Apex horizontal, Zusatzpunkte für Draw/Fade) + Easing-Timing.
- Renderer: Farbe, Dicke, Verjüngung, Glow, weißer Kern, Schatten, Ball-Punkt, Modi „voller Pfad“ und
  „Schweif“, Halten + Ausblenden nach Landung, Okklusions-Eingang (für Phase 3).
- Export: ProRes 4444 mit Alpha, PNG-Sequenz, eingebrannt H.264/H.265 (mit Audio).
- Projektdatei `<clip>.kpmntrace.json` (speichern/laden, relative Pfade).
- GUI: Vorschau mit Zoom/Pan, Timeline mit Markern, Frame-Schritt, Abspielen, Werkzeuge
  Start/Apex/Landung/Zusatzpunkt/Korrektur, Punkte ziehen, Undo/Redo, Style-Panel, Export im
  Hintergrund mit Fortschritt + Abbrechen, Drag & Drop.
- CLI: `probe`, `export`, `gui`.
- Synthetischer Videogenerator (`tools/synth.py`) mit Ground Truth; Abnahme-Skript
  `tools/verify_overlay.py`.

**Abnahme:** `tests/test_export.py` – synthetischer Stativ-Clip → ProRes-Overlay → per Skript über das
Original gelegt: Alpha auf dem gesamten erwarteten Pfad > 0.5, Frameanzahl Overlay == Original,
dekodiertes Overlay == direktes Rendering (±2/255).

## Phase 2 – erledigt
- `camera/features.py`: goodFeaturesToTrack (Ränder/Personenmaske ausgeschlossen), LK mit
  Forward-Backward-Check; Features werden jeden Frame neu detektiert (nachgefüllt).
- `camera/tracker.py`: Homographie pro Frame zum Impact-Frame (vorwärts + rückwärts), Verkettung +
  direkte Nachregistrierung gegen den Referenz-Frame, Konfidenz pro Frame, Stativ-Erkennung.
- `camera/smoothing.py`: Spike-Ausreißer + konfidenzgewichteter RTS-Kalman.
- `camera/shot_camera.py`: Tracking-Bereich pro Schlag (Impact − 0,5 s … Landung + 2,5 s),
  Umrechnung Proxy → Quellpixel, Ablage im Schlag (Projektdatei).
- Renderer/Export projizieren den im Referenz-Frame definierten Tracer pro Frame mit der inversen
  Homographie.
- GUI: „Kamera tracken (T)“ / „Erzwingen“, Status, unsichere Frames rot in der Timeline,
  Konfidenz in der Vorschau, Korrektur-Werkzeug (K) mit lokalen Keyframes.

**Abnahme:** `tests/test_camera.py::test_tracker_accuracy_on_shaky_zooming_clip` – synthetischer Clip
mit Wackeln (8 px), Rotation, 20 % Zoom und Schwenk: mittlerer Tracer-Positionsfehler ≈ 0,03 px
(gefordert ≤ 2 px). Weitere Tests: Ausreißer-Überbrückung, unbrauchbare Frames → niedrige Konfidenz,
Stativ-Erkennung.

## Bekannte Punkte / offen
- HDR-Tonemapping (hable) ist nur für die Analyse/Vorschau gedacht; eingebrannte Exporte sind SDR.
- Die GUI-Screenshots/Tests laufen im Offscreen-Modus; echte iPhone-Clips wurden noch nicht getestet
  (keine Testclips im Repo).
