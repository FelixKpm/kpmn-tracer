# Fortschritt

| Phase | Status |
|---|---|
| 1 – Fundament: Import, Vorschau, manueller Tracer, Export | ✅ fertig |
| 2 – Handheld: Kamerabewegung kompensieren | ✅ fertig |
| 3 – Personen-Maske | ✅ fertig |
| 4 – Automatische Impact-Erkennung | ✅ fertig |
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

## Phase 3 – erledigt
- `segmentation/segmenter.py`: MediaPipe-Segmentierer (multiclass / pose / deeplab) hinter einem
  `PersonSegmenter`-Protokoll (in Tests durch Ground-Truth bzw. Fakes ersetzbar).
- `segmentation/mask_cache.py`: `MaskTrack` – jeder n-te Frame, Interpolation, NPZ-Cache,
  Tracking-Ausschlussmaske und weiche Okklusions-Matte.
- `segmentation/provider.py`: Masken pro Schlag-Bereich berechnen/laden, Funktionen für Tracker und
  Export.
- Kamera-Tracking ignoriert Features in der Personenmaske (GUI berechnet Masken automatisch vor dem
  Tracking; abschaltbar über `settings.use_person_mask`).
- Option „Tracer hinter Golfer“ pro Schlag: Vorschau und Export schneiden den Tracer weich aus.

**Abnahme:** `tests/test_segmentation.py` – synthetischer Handheld-Clip mit großer, texturierter,
bewegter „Person“: Kamera-Fehler ohne Maske ≈ 13 px, mit Maske ≈ 0,03 px. Okklusion im ProRes-Export
und in der GUI-Vorschau geprüft (Alpha im Personenbereich 0, außerhalb unverändert).

## Phase 4 – erledigt
- `ball/audio_onsets.py`: Transienten-Erkennung (Hochpass, Log-Energie, Anstieg + Prominenz,
  Mindestabstand, sample-genaue Onset-Zeit).
- `ball/impact.py`: Ball-Lokalisierung (Top-Hat-Blob nahe Hinweis), Präsenz-Signal über den ganzen
  Clip, Übergänge anwesend → dauerhaft abwesend, Fusion mit Audio, mehrere Schläge pro Clip.
- `ClipSession.frame_times()/time_to_frame()`: exakte Zeit→Frame-Zuordnung, auch bei VFR.
- GUI: „Impacts erkennen (D)“, Kandidaten als Magenta-Marker in der Timeline (anklickbar),
  „Kandidat übernehmen“ / „Alle sicheren übernehmen“ (legt Schläge mit lokalisiertem Startpunkt an),
  Impact verschieben über „Impact = Frame“.
- Generator: Schlägerkopf, der beim Impact durch den Ball fährt; Fremdgeräusche aus der Nachbarbox.

**Abnahme:** `tests/test_impact.py` – Clip mit 3 Schlägen, Schläger, Kamerawackeln und 3
Fremdschlag-Geräuschen: alle 3 Impacts exakt (±0 Frames, gefordert ±1), Fremdgeräusch bei ruhendem
Ball verworfen, die anderen mit Konfidenz 0,15. Zusätzlich: nur Audio, nur Video (ohne Tonspur), 60
und 120 fps, VFR-Zeitzuordnung.

## Bekannte Punkte / offen
- HDR-Tonemapping (hable) ist nur für die Analyse/Vorschau gedacht; eingebrannte Exporte sind SDR.
- Masken werden für lange Bereiche komplett in den Speicher geladen (~230 KB/Key-Frame); für
  Schlag-Bereiche unkritisch.
- Impact-Erkennung per Video setzt einen hellen Ball voraus (Range-Bälle sind weiß/gelb); der
  Abschlagpunkt sollte zwischen den Schlägen gleich bleiben (Matte/Tee).
- Die GUI-Screenshots/Tests laufen im Offscreen-Modus; echte iPhone-Clips wurden noch nicht getestet
  (keine Testclips im Repo).
