# Fortschritt

| Phase | Status |
|---|---|
| 1 – Fundament: Import, Vorschau, manueller Tracer, Export | ✅ fertig |
| 2 – Handheld: Kamerabewegung kompensieren | ⏳ offen |
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

## Bekannte Punkte / offen
- HDR-Tonemapping (hable) ist nur für die Analyse/Vorschau gedacht; eingebrannte Exporte sind SDR.
- Die GUI-Screenshots/Tests laufen im Offscreen-Modus; echte iPhone-Clips wurden noch nicht getestet
  (keine Testclips im Repo).
