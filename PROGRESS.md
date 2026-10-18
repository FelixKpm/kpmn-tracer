# Fortschritt

| Phase | Status |
|---|---|
| 1 – Fundament: Import, Vorschau, manueller Tracer, Export | ✅ fertig |
| 2 – Handheld: Kamerabewegung kompensieren | ✅ fertig |
| 3 – Personen-Maske | ✅ fertig |
| 4 – Automatische Impact-Erkennung | ✅ fertig |
| 5 – Automatisches Ball-Tracking | ✅ fertig |
| 6 – Optional: ML-Ballerkennung | ✅ fertig (optional, nicht Standard – D26) |
| 7 – Workflow & Komfort | ✅ fertig |
| 8 – Packaging & Doku | ✅ fertig |

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

## Phase 5 – erledigt
- `ball/flightfit.py`: perspektivisches Flugmodell, RANSAC + robuste Nachoptimierung, Apex, Landung.
- `ball/candidates.py`: `BallDetector`-Interface + `ClassicDetector` (stabilisierte ROI, Differenz zu
  f±k, beide Polaritäten, Gradienten-Toleranz, Blob-Filter, Personenmaske).
- `ball/tracker.py`: Mehrhypothesen-Initialisierung, Verfolgung mit wachsendem Suchfenster und
  Lückenüberbrückung, globaler Fit + Nachsuche entlang der Kurve.
- `ball/auto.py`: finale Flugbahn (Spline + Extrapolation), Konfidenz, Überführung in Anker mit
  Zeiten bzw. vorbefüllter manueller Modus.
- `analysis.py`: Pipeline pro Schlag (Maske → Kamera → Ball) und pro Clip (Impacts → Schläge).
- GUI: „Ball tracken (B)“, „Ganzen Clip analysieren“, „Vereinfachen“.
- Impact-Erkennung: Video-Kandidaten brauchen einen bestätigten Abflug (siehe D25).

**Abnahme:** `tests/test_ball_tracking.py` – synthetische Clips (Stativ, Handheld, Ball 1–4 px, Lücke
von 0,5 s, Ball ab 2 s unsichtbar, schwacher Kontrast), Startpunkt absichtlich 1,8 px daneben
geklickt: mittlerer Fehler des gerenderten Tracer-Kopfs 0,1–0,5 px (gefordert ≤ 3 px), Landezeit
±6 %. Echter Clip (D25): Ball eines echten Schlags sauber verfolgt (Konfidenz 0,84).

## Phase 6 – erledigt (schlank, optional)
- `ball/ml_detector.py`: `YoloDetector` (Kachel-Inferenz, CPU/GPU automatisch) und `CombinedDetector`
  hinter dem `BallDetector`-Interface; Auswahl über Projekteinstellungen.
- `ball/dataset.py`, `tools/make_ball_dataset.py`: Trainingsdaten aus eigenen Clips (YOLO-Format).
- `tools/label_balls.py`: Label-Werkzeug; `tools/train_yolo.py`: Training; `requirements-ml.txt`.
- Lizenzen von Ultralytics und öffentlichen Datensätzen in DECISIONS.md (D26).
- Tests (`tests/test_ml.py`) laufen ohne Ultralytics (Fake-Modell mit identischem `predict`-Vertrag);
  einmalig mit echtem Ultralytics/CPU verifiziert (D26).

## Phase 7 – erledigt
- Batch (`kpmn_tracer/batch.py`): Ordner → alle Clips analysieren → Projektdateien + Thumbnails +
  CSV-Übersicht → bestätigte Schläge exportieren. GUI: Batch-Fenster (Strg+B) mit Review-Liste
  (Thumbnail mit Tracer, Konfidenz, Häkchen = bestätigt, Doppelklick = im Editor öffnen, „alle über
  Schwelle bestätigen“, Export). CLI: `analyze`, `batch [--auto-confirm --export]`, `batch-export`.
- Style-Presets (eingebaut + eigene, speichern/laden/löschen im Style-Panel).
- Positions-Preset für den Stativplatz (Ballstart + Kurvenform, normiert), automatisch gemerkt.
- Text-Einblendung pro Schlag (z. B. Schläger, Carry), animiert (Fade + Slide), Position am
  Apex/Landepunkt oder in einer Ecke, im Alpha-Export enthalten.
- Tastenkürzel für alle häufigen Aktionen, Übersicht mit F1; Einstellungsdialog (Strg+,).
- Alle langen Analysen laufen im Hintergrund mit Fortschritt und Abbrechen.
- Lint mit ruff, alle Checks grün.

**Tests:** `tests/test_batch.py` (Ordner mit 2 Clips × 2 Schlägen: alle Impacts exakt, Konfidenz
≥ 0,8, Review, Export nur bestätigter, CLI) und GUI-Tests für Presets, Text, Bestätigen, Batch-Fenster.

## Phase 8 – erledigt
- `packaging/kpmn_tracer.spec` + `tools/build_windows.py`: Ordner-Build mit `KPMN Tracer.exe` (GUI)
  und `kpmn-tracer.exe` (CLI), FFmpeg und MediaPipe-Modelle im Build, ZIP für die Weitergabe.
- Build-Prüfung: CLI-Selbsttest und GUI-Smoke-Test laufen automatisch nach jedem Build (beide grün).
- App-Icon (`tools/make_icon.py`), Log in `~/.kpmn_tracer`.
- README: Installation, Bedienung (manuell, automatisch, Batch), Resolve-Workflow (Overlay auf V2,
  Composite „Normal“), Troubleshooting (VFR, HDR-Farben, Tracking/Impact schlägt fehl, FFmpeg),
  CLI, Dateien, Lizenzen.

## Nachtrag 1 – erster echter Nutzer-Clip (IMG_2335.MOV)
Gemeldet: manueller Tracer hängt bis zum Apex hinter dem Ball her, auch mit Start-Tempo 10.
- Ursache analysiert (D32), sechs Fehler/Schwächen behoben (D33–D35).
- Neues Werkzeug „Ball hier“ (H) für den manuellen Modus, Easing-Grenzen erweitert.
- Vollautomatisch: „Ganzen Clip analysieren“ findet genau den einen Schlag (Frame 708, Ton + Video
  + Abflug, Konfidenz 1,0); Probeschwung und Nachbarboxen liegen unter 50 %. Ball von Frame 709 bis
  768 verfolgt, danach bis zur geschätzten Landung (805) extrapoliert.
- Regressionstests: Zeit-Pins, zwei Schläge 0,42 s nacheinander, naher schneller Abflug,
  Template-Frame ≠ 0.

## Nachtrag 2 – Nutzer-Feedback nach vielen Test-Clips (v0.2.0)
Gemeldet: „alte Daten im neuen Video“, Automatik bei IMG_2366 (Wedge, aus der Hand) völlig
daneben; gewünscht: Frame mit Tracer als Bild, Scorecard-Generator mit austauschbaren Designs.
- Ursache „alte Daten“: Ballposition des letzten Clips wurde ungefragt übernommen (D36) → nur noch
  auf Wunsch; Projekt zurücksetzen; Hinweis beim Laden; Batch-Schalter.
- Ball-Tracker für steile, nahe Abflüge (D37): IMG_2366 jetzt 55 Detektionen, Konfidenz 0,76.
- Einzelbild-Export in Originalauflösung mit Tracer (D38): GUI, CLI `still`.
- Scorecard Studio mit Design-System, NightRange als Vorlage (D39): *Extras*, CLI `scorecard`.
- Tests: steiler Abflug mit den gemessenen Ballpositionen, Einzelbild (CFR/VFR/gedreht/Tracer),
  Projekt zurücksetzen, Scorecard-Designs.

## Definition of Done – Abgleich
| Kriterium | Stand |
|---|---|
| Stativ- und Handheld-Clip importieren, Ball automatisch getrackt oder mit wenigen Klicks korrigiert | ✅ synthetisch (≤ 0,5 px) und an einem echten CC0-Clip geprüft; iPhone-Clips des Nutzers noch nicht |
| Overlay mit Alpha liegt frame-genau über dem Original | ✅ Frameanzahl/Auflösung/Rate identisch, per Skript zurückgelegt geprüft; VFR wie Resolve (1:1) |
| Batch-Verarbeitung einer Range-Session | ✅ GUI + CLI, Review, Export bestätigter Schläge |
| Alle Tests grün, PROGRESS zeigt alle Phasen erledigt, README erklärt die Nutzung | ✅ 112 Tests (inkl. HDR-HLG-Hochformat), ruff sauber |

## Bekannte Punkte / offen
- HDR-Tonemapping (hable) ist nur für die Analyse/Vorschau gedacht; eingebrannte Exporte sind SDR.
- Masken werden für lange Bereiche komplett in den Speicher geladen (~230 KB/Key-Frame); für
  Schlag-Bereiche unkritisch.
- Impact-Erkennung per Video setzt einen hellen Ball voraus (Range-Bälle sind weiß/gelb); der
  Abschlagpunkt sollte zwischen den Schlägen gleich bleiben (Matte/Tee).
- Video-only-Impact-Erkennung ist auf echtem Material (ohne Ton) noch unzuverlässig (D25); mit Ton
  bzw. per Klick auf den Schlag funktioniert der Ablauf.
- Starker Luftwiderstand/Auftrieb wird nur im beobachteten Teil exakt wiedergegeben; die
  Extrapolation nach dem Verschwinden des Balls ist eine Schätzung (Landepunkt zum Nachkorrigieren).
- Die GUI-Tests laufen im Offscreen-Modus; echte iPhone-Clips des Nutzers wurden noch nicht
  getestet (nur ein CC0-Clip, siehe D25).
- Empfehlung für den nächsten Schritt: ein paar echte iPhone-Clips (Stativ + Hand, HDR, VFR,
  Hoch- und Querformat) durch `kpmn-tracer.exe batch` laufen lassen; Ergebnisse/Fehlfälle zeigen, ob
  Parameter nachgeschärft oder die optionale ML-Erkennung trainiert werden sollte.
