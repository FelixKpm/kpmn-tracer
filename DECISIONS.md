# Architektur- und Library-Entscheidungen

Kurz begründet, chronologisch. Neue Einträge unten anhängen.

## D1 – Python 3.13 statt 3.11
Auf dem Entwicklungsrechner ist nur Python 3.13 installiert. Alle Abhängigkeiten (PySide6, OpenCV,
SciPy, MediaPipe ≥ 0.10.30) haben 3.13-Wheels. Code nutzt nur 3.11-kompatible Syntax
(`requires-python >= 3.11`).

## D2 – FFmpeg: statischer BtbN-Build in `vendor/`, `imageio-ffmpeg` nur als Fallback
`imageio-ffmpeg` liefert nur `ffmpeg`, kein `ffprobe` – der wird aber für die Metadaten (Rotation,
VFR, HDR) gebraucht. `tools/fetch_ffmpeg.py` lädt den GPL-Build 8.1 von BtbN (enthält `prores_ks`,
`libx264`, `libx265`, `zscale`/`tonemap`). Suchreihenfolge: `$KPMN_FFMPEG_DIR` → PyInstaller-Bundle →
`vendor/ffmpeg/bin` → `PATH` → imageio-ffmpeg. `vendor/` ist nicht im Git (Binaries), wird für den
Build automatisch geholt. Lizenz: GPL-Build, weil x264/x265 GPL sind; die App wird nicht verkauft,
die FFmpeg-Lizenz wird im Build mitgeliefert.

## D3 – Analyse-Proxy (MJPEG/AVI) statt direktem Seek im Original
iPhone-HEVC mit langen GOPs lässt sich nicht schnell und frame-genau seeken. Beim Import wird einmalig
ein Proxy erzeugt: 8-bit SDR (HDR per `zscale`+`tonemap=hable`), Rotation angewendet, konstante
Framerate, längste Seite ≤ 1920 px, MJPEG (nur Keyframes ⇒ jeder Seek ist exakt und billig).
Das Original wird nie verändert. Cache: `<clip-ordner>/.kpmn_cache/<name>_<hash>/`.
Alle Projektkoordinaten sind in **Quell-Pixeln (Anzeigeorientierung)**; Proxy-Skalierung nur intern.

## D4 – VFR: Frame-Index-Mapping wie DaVinci Resolve (Standard), Zeit-Resampling optional
Resolve „conformt“ VFR-Clips, indem es jeden gespeicherten Frame nacheinander mit der nominellen Rate
abspielt (deshalb der bekannte Audio-Drift bei iPhone-VFR in Resolve). Damit das Overlay dort
frame-genau sitzt, muss Overlay-Frame *i* = Quell-Frame *i* sein. Standard (`vfr_mode="frames"`):
jeder Frame wird behalten und per `setpts=N/(fps*TB)` auf konstante Rate gelegt – keine Duplikate,
keine Drops. Die Ziel-Rate ist die auf eine Standardrate gerundete mittlere Rate. Alternativ
`vfr_mode="resample"` (zeitbasiert, `-fps_mode cfr`), falls der Clip vorher in eine CFR-Datei
konvertiert wurde. Die GUI zeigt VFR + Zielrate in der Statusleiste.

## D5 – Kurvenmodell: Hermite-Spline durch Anker + separates Timing
Geometrie und Zeit sind getrennt:
* **Pfad** `P(u)`: stückweise kubischer Hermite-Spline durch alle Anker (Start, optionale Punkte,
  Apex, optionale Punkte, Landung). Am Apex horizontale Tangente (Apex ist wirklich der höchste
  Punkt), innen Catmull-Rom, an Start/Landung einseitige Sehne, die per *Start-/Abstiegs-Steilheit*
  steiler gemacht wird. Zusätzliche Punkte = der „zusätzliche Kontrollpunkt“ für Draw/Fade.
* **Timing** `u(τ)`: manuell über eine Easing-Kurve mit Geschwindigkeitsprofil
  `v(τ) = 1 + a·e^(−τ/d) + b·τ²` (schnell nach Impact, langsam am Apex, wieder schneller), oder –
  wenn jeder Anker eine Zeit hat (Auto-Tracking) – monotone PCHIP-Interpolation durch die gemessenen
  Zeiten.
Damit nutzen manueller und automatischer Modus **dieselbe** Datenstruktur (`Shot` mit Ankern).
Ein Bezier-Ansatz wurde verworfen, weil er nicht garantiert durch den Apex läuft bzw. dort nicht
horizontal ist.

## D6 – Renderer: Polygon-Stroke mit Sub-Pixel-AA, nur in der Bounding-Box
Variable Linienbreite (Verjüngung) ist mit `cv2.polylines` nicht möglich. Der Strich wird als
Polygon (linke/rechte Offsetkurve + runde Kappen) mit `LINE_AA` und 4 Bit Sub-Pixel-Genauigkeit
gefüllt. Glow = zwei Gauß-Blurs der Kernmaske, Schatten = verschobene, geblurrte Maske, optional
weißer Kern. Komposition prämultipliziert („over“), Ausgabe RGBA mit *straight alpha* (was ProRes
4444 und PNG erwarten). Gerechnet wird nur im Rechteck um den Tracer – 4K-Overlays bleiben schnell.
Größen im Style sind auf 1080 px kurze Seite normiert und skalieren mit der Auflösung.

## D7 – Export über FFmpeg-Pipe
Overlay-Frames werden roh (`rgba`) an FFmpeg gepipet: ProRes 4444 (`prores_ks -profile:v 4
-pix_fmt yuva444p10le`), PNG-Sequenz direkt über OpenCV. Eingebrannte Exporte lassen FFmpeg selbst
Original (gleiche Normalisierung wie der Proxy) und Overlay per `overlay`-Filter mischen; Audio wird
übernommen. stderr geht in eine Temp-Datei (kein Pipe-Deadlock).

## D8 – Modul `kpmn_tracer/trace/` zusätzlich zur vorgeschlagenen Struktur
Datenmodell (`Shot`, Anker, Kamera-Track, Korrektur-Keyframes), Pfad und Timing sind weder reine
Ball-Erkennung noch Rendering. Sie liegen deshalb in einem eigenen Paket `trace/`, das von `ball/`
(Auto-Tracking), `render/` und `gui/` gleichermaßen benutzt wird.

## D9 – GUI-Threading: Relay-Objekt im GUI-Thread
In PySide6 laufen an Signale gebundene Lambdas im Thread des Senders. Lange Aufgaben laufen in
`QThread`-Workern; deren Signale werden über ein `TaskHandle`-Objekt im GUI-Thread (queued)
weitergereicht, sodass Callbacks immer im GUI-Thread laufen.

## D10 – Kamera-Tracking: Verkettung + direkte Nachregistrierung in *jedem* Frame
Frame-zu-Frame-LK (Forward-Backward-Check, MAGSAC-Homographie) liefert eine Vorhersage
`H(f→ref)`. Danach wird Frame *f* mit dieser Vorhersage in die Referenzgeometrie gewarpt und die
Referenz-Features direkt hineingetrackt; die Rest-Homographie korrigiert die Vorhersage. Das
eliminiert Drift vollständig und ist bei Proxy-Auflösung schnell genug (~30 ms/Frame bei 1280×720),
deshalb Standard `refine_every = 1` statt „regelmäßig“. Gemessen auf synthetischem Clip mit 8 px
Wackeln, 0,6° Rotation, 20 % Zoom und Schwenk: mittlerer Fehler ≈ 0,03 px (Abnahme: ≤ 2 px).
Konfidenz = RANSAC-Inlier-Anteil der direkten Registrierung, gedämpft bei < 60 Stützpunkten.

## D11 – Glättung: Spike-Erkennung + konfidenzgewichteter RTS-Kalman auf Eckpunkt-Parametern
Ein klassischer gleitender Mittelwert würde echtes Handwackeln wegglätten – der Tracer muss diesem
aber folgen. Deshalb: Parametrisierung über die 4 abgebildeten Bildecken (8 Werte), Ausreißer =
isolierte Spikes in der 2. Differenz gegen eine *globale* robuste Skala (iterativ, größter zuerst),
dann ein Constant-Velocity-Kalman mit RTS-Rückwärtslauf, dessen Messrauschen mit `1/Konfidenz²`
skaliert. Gute Frames bleiben praktisch unverändert, schlechte/Ausreißer werden aus den Nachbarn
überbrückt.

## D12 – Stativ-Erkennung vorab per Stichprobe
Vor dem vollen Tracking werden ~10 Frames direkt gegen den Referenz-Frame registriert. Bewegt sich
keine Bildecke mehr als 0,6 px (Proxy), gilt der Clip als Stativ und das Tracking wird
übersprungen (Button „Erzwingen“ in der GUI umgeht das).

## D13 – Korrektur-Keyframes bleiben lokal
Eine Korrektur verschiebt den projizierten Tracer in einem Frame. Damit sie nicht den ganzen Rest
des Clips verschiebt, werden beim ersten Keyframe automatisch Null-Keyframes an den nächsten gut
getrackten Frames davor/danach gesetzt; dazwischen wird linear interpoliert.

## D14 – `opencv-contrib-python` statt `opencv-python`
MediaPipe 1.x hängt von `opencv-contrib-python` ab. Beide Pakete installieren dasselbe `cv2`-Modul
und überschreiben sich gegenseitig. Deshalb wird nur `opencv-contrib-python` (Obermenge) verwendet.

## D15 – Personen-Segmentierung: MediaPipe „selfie_multiclass_256x256“ als Standard
Verglichen auf einem echten Golf-Foto (Golfer von hinten, Durchschwung) und auf einer kleinen,
weiter entfernten Person:

| Modell | Golfer groß | Golfer klein (~40 px) | Zeit (640 px) |
|---|---|---|---|
| Pose-Landmarker (Segmentierungsausgabe) | sehr gut, ohne Schläger | **nicht erkannt** | ~45 ms |
| DeepLab v3 (Klasse „person“) | gut, Ränder grob | **nicht erkannt** | ~60 ms |
| Selfie multiclass (1 − Hintergrund) | sehr gut, **inkl. Schläger** | erkannt | ~160 ms |

Multiclass ist das einzige Modell, das auch kleine Golfer findet, und der mitsegmentierte Schläger
ist für beide Zwecke erwünscht (bewegt sich → nicht tracken; Tracer läuft dahinter). Modell ist
über `project.settings["mask_model"]` umschaltbar (`pose`, `deeplab`). Modelle liegen in
`vendor/models` (`tools/fetch_models.py`), werden nicht ins Git eingecheckt (Lizenz Apache 2.0).

## D16 – Masken nur jeden 2. Frame, nur wo gebraucht, Cache als NPZ
Segmentiert wird jeder `mask_stride`-te Frame (Standard 2) bei max. 640 px, dazwischen wird linear
überblendet. Berechnet wird nur der Bereich, den ein Schlag braucht (Tracking-Bereich bzw.
Impact … Landung + Halten + Ausblenden), inkrementell ergänzt und als
`<cache>/masks_<modell>_s<stride>.npz` gespeichert (das Projekt merkt sich nur die Einstellungen).
Tracking-Ausschluss: Wahrscheinlichkeit > 0,35, um 6 px dilatiert (plus 15 px im Feature-Detektor).
Okklusion: weiche Matte (Rampe 0,3…0,7, Gauß-Feather ~2 px @1080).

## D17 – Definition „Impact-Frame“
Impact-Frame = letzter Frame, in dem der Ball noch ruhig am Startpunkt liegt (der Kontakt passiert
zwischen ihm und dem nächsten Frame). Dort beginnt der Tracer mit Kopf am Startpunkt. Audio-Zeit
*t* → Frame, der zum Zeitpunkt *t* angezeigt wird (letzter Frame mit pts ≤ t). Bei VFR im
`frames`-Modus werden dafür die echten Paket-Zeitstempel verwendet (`ClipSession.frame_times`,
im Cache), plus Startversatz der Audiospur.

## D18 – Audio-Onsets: Hochpass + 1-ms-Log-Energie, Anstieg *und* Abstand zum Grundrauschen
Schlaggeräusche sind kurz, laut und breitbandig. Hochpass 1,5 kHz entfernt Wind, Stimmen, Brummen.
Kandidat = Anstieg ≥ 12 dB in 4 ms *und* Spitze ≥ 18 dB über dem gleitenden Median (1 s);
mindestens 0,6 s Abstand (Echo/Nachhall wird verworfen). Onset-Zeit sample-genau: erstes Sample
über 25 % der lokalen Spitze. Ergebnis auf synthetischen Signalen: < 1,5 ms Fehler.

## D19 – Video-Signal: Kontrast des weißen Balls statt Korrelation
Erster Ansatz (NCC eines Ball-Templates) trennt bei kleinen Bällen schlecht, weil die
Hintergrundtextur mitkorreliert (abwesend ≈ 0,6 vs. anwesend 1,0). Stattdessen: Spitze des
White-Top-Hat am Ballort relativ zum Klick-Frame. Anwesend ≈ 1,0, abwesend/Schläger ≈ 0,1. Die ROI
folgt langsamer Kamerabewegung per Phasenkorrelation auf einer 320-px-Verkleinerung.
Fusion: Audio + Video innerhalb ±0,25 s → Audio-Frame (sample-genau); nur Audio, Ball blieb liegen →
verworfen (Nachbarbox); nur Audio, Abschlagpunkt leer → Konfidenz 0,15; nur Video → 0,55.

## D20 – Flugmodell: perspektivisch projizierte Parabel mit festem Startpunkt
`x(t) = (Sx + a1·t + a2·t²)/(1 + c·t)`, `y` analog, gemeinsamer Nenner = linear wachsende Tiefe
(Ball fliegt von der Kamera weg). Herleitung: luftwiderstandsfreie 3-D-Parabel durch eine Lochkamera.
Vorteile gegenüber einer Bildschirm-Parabel: erklärt das starke Abbremsen im Bild (156 → 86 → 54
px/Frame direkt nach dem Abflug), extrapoliert stabil, ist nach Multiplikation mit dem Nenner linear
(RANSAC mit 3 Punkten), Landezeitpunkt analytisch (Ball wieder auf Bodenhöhe:
`t = (cy·c − b1)/b2`). Luftwiderstand/Auftrieb sind nicht modelliert – deshalb D23.

## D21 – Kandidaten: Differenz zu *beiden* Nachbarn, beide Polaritäten, Gradienten-Toleranz
`min(f − (f−k), f − (f+k))` lässt nur Dinge übrig, die in *f* auftauchen und in beiden Nachbarn
fehlen (bewegter Ball), statische Struktur und Rauschen heben sich auf. Gespiegelt für dunkle Bälle
vor hellem Himmel (im echten Clip wechselt die Polarität beim Übergang Rasen → Himmel). Nach dem
Warpen erzeugen Kanten (Baumreihe!) durch Rest-Fehlregistrierung Differenzen proportional zum
Gradienten; die Schwelle wird deshalb lokal um `0,6 px × Gradient` angehoben: Fehlkandidaten pro
Frame von ~450 auf < 10. Pixel außerhalb eines der drei Quellbilder werden ignoriert.

## D22 – Initialisierung mit mehreren Abflug-Hypothesen
Beim Impact verlassen mehrere Dinge den Ballort (Ball, Schlägerkopf, Divot). Ein einzelnes RANSAC
wählte im echten Clip den Schlägerkopf (zwei Blobs pro Frame = doppelte Inlier). Jetzt: Inlier
zählen pro *Frame*, Ziehen gewichtet nach Kontrast und Größenähnlichkeit zum ruhenden Ball, bis zu 6
unterschiedliche Hypothesen werden verfolgt, gewonnen hat die längste, dichteste, glatteste Bahn
(der Schlägerkopf beschreibt einen Kreisbogen und fällt aus dem Modell).

## D23 – Finale Flugbahn: Glättungsspline (beobachtet) + perspektivisches Modell (Extrapolation)
Bei starkem Luftwiderstand weicht das globale Modell im beobachteten Teil bis 8 px ab, obwohl die
Detektionen auf ~0,15 px genau sind. Deshalb: im beobachteten Bereich ein Glättungsspline mit
GCV-gewählter Stärke (überbrückt Lücken, entfernt Jitter), danach das zum Flugende hin gewichtete
Modell, stetig angeschlossen, bis zur geschätzten Landung. Das Ergebnis wird als Anker mit Zeiten in
die normale `Shot`-Struktur geschrieben (dicht direkt nach dem Impact, dann alle ~0,1 s); „Vereinfachen“
reduziert es auf Start/Apex/Landung mit passend gewählter Easing-Kurve.

## D24 – Konfidenz und Rückfall in den manuellen Modus
Konfidenz = Anzahl Detektionen × beobachtete Dauer (≥ 0,8 s) × √Abdeckung × Fit-Qualität. Unter 0,5
wird der Schlag mit Start, geschätztem Apex und geschätzter Landung *ohne* Zeiten vorbefüllt (manuelles
Timing), ohne Fund mit einer typischen Kurvenform ab dem Startpunkt.

## D25 – Echtclip-Prüfung (CC0-Video von Wikimedia Commons, `tools/real_clip_check.py`)
Zeitlupen-Zusammenschnitt einer Range-Session, Hochformat, VFR, Ton nicht nutzbar.
* Ball-Tracking eines echten Schlags (Impact + Startklick): 109 Detektionen über 156 Frames,
  Konfidenz 0,84, Tracer sitzt glatt auf dem Ball (Polaritätswechsel vor dem Himmel funktioniert).
* Reine Video-Impact-Erkennung liefert dort Fehlalarme (Schläger beim Ansprechen über dem Ball,
  herangerollter Ball, Kameraschwenk, Schnitt). Ein Video-Kandidat wird nur bestätigt, wenn vorher ein
  Ball 0,5 s stabil an der Stelle lag *und* ein verfolgbarer, steigender Flug (≥ 8 Detektionen,
  ≥ 0,4 s) folgt; Kamera dabei mit dem Phase-2-Tracker kompensiert. Das senkt die Fehlalarme von 9 auf
  1, verpasst aber in diesem Clip den echten Schlag. Video-only-Kandidaten bekommen daher höchstens
  0,55, unbestätigte 0,2. Bei normalen iPhone-Clips ist der Ton der Hauptpfad.

## D26 – Phase 6 schlank: ML als optionales, austauschbares Modul
Die Spezifikation macht Phase 6 davon abhängig, ob Phase 5 auf echten Clips reicht. Auf dem
verfügbaren echten Clip reichte das klassische Tracking (D25); Clips des Nutzers liegen noch nicht
vor. Deshalb ist die ML-Erkennung vollständig vorbereitet, aber **nicht** Standard und **nicht** im
Build:
* `YoloDetector` implementiert dasselbe `BallDetector`-Interface und arbeitet auf der stabilisierten
  ROI → Kandidaten fließen in denselben Tracker/Fit. `CombinedDetector` vereinigt klassisch + YOLO.
  Auswahl über `project.settings["detector"]` = `classic` | `yolo` | `both` und `yolo_model`.
* Inferenz in **nativen Kacheln** (Trainingsgröße, Überlappung 32 px): Ein auf 640 px herunter-
  bzw. ein kleines Suchfenster auf 320 px hochskalierter Ball wird nicht erkannt (gemessen: erst 9
  bzw. 17 Detektionen, mit Kacheln 95 von 96).
* CPU-Fallback: `device="auto"` → CUDA falls vorhanden, sonst CPU. Verifiziert mit Ultralytics 8.4 /
  PyTorch 2.14 (CPU): Mini-Training (YOLO11n, 15 Epochen, 525 Kacheln) ≈ wenige Minuten, mAP50 0,97;
  Pipeline nur mit YOLO: 0,42 px Fehler, ~11 s pro Schlag.
* Trainingsdaten aus den eigenen Clips (`kpmn_tracer/ball/dataset.py`, `tools/make_ball_dataset.py`):
  Kacheln um die Ballposition bestätigter/sicherer Schläge + Negativ-Kacheln, YOLO-Labels;
  Prüfen/Korrigieren mit `tools/label_balls.py`; Training mit `tools/train_yolo.py`.

**Lizenzen:**
* Ultralytics YOLO: **AGPL-3.0** (bzw. kommerzielle Enterprise-Lizenz). Für private Nutzung
  unproblematisch; beim Weitergeben einer .exe *mit* Ultralytics gelten die AGPL-Pflichten
  (Quellcode). Deshalb nur optional (`requirements-ml.txt`) und vom PyInstaller-Build ausgeschlossen.
* Öffentliche Golfball-Datensätze auf Roboflow Universe, z. B. „Golf Balls“
  (golf-balls/golf-balls-qujpk) und „golf project new“ (golfball-is8fc/golf-project-new): jeweils
  **CC BY 4.0** (Namensnennung nötig); „golf ball detection“ (golfballtracker/golf-ball-detection-evnld):
  **MIT**. Lizenz wird je Uploader gesetzt und muss auf der jeweiligen Seite vor Nutzung bestätigt
  werden. Diese Datensätze zeigen meist große, nahe Bälle (Schlagposition, Grün) – für winzige Bälle
  im Flug sind eigene Daten aus dem Datensatz-Werkzeug passender; die öffentlichen Daten eignen sich
  zum Vortrainieren.

## D27 – Presets im Benutzerordner, Positions-Preset normiert
Styles, Positions-Preset und App-Standards liegen in `~/.kpmn_tracer` (überschreibbar mit
`$KPMN_HOME`, Tests nutzen immer ein Temp-Verzeichnis). Das Positions-Preset speichert Ballstart und
grobe Kurvenform in Bruchteilen von Breite/Höhe – derselbe Stativplatz passt so auch bei anderer
Auflösung. Es wird beim Speichern eines Projekts automatisch aktualisiert (Auto-Ergebnisse vorher
auf Start/Apex/Landung vereinfacht) und von „Neuer Schlag“ sowie dem Batch genutzt.

## D28 – Text-Overlays mit Qt gerendert
OpenCV-Schriften können keine Umlaute/Proportionalschrift und sehen unprofessionell aus. Die Labels
werden mit `QPainter` in ein `QImage` gerendert (gecacht), entmultipliziert und in das RGBA-Overlay
gemischt – damit sind sie automatisch im Alpha-Export enthalten. Ohne laufende GUI (CLI/Batch) wird
eine Offscreen-`QGuiApplication` erzeugt; dafür muss `QT_QPA_FONTDIR` auf den System-Schriftordner
zeigen (sonst nur Kästchen) – wird automatisch gesetzt.

## D29 – Batch: Ergebnisse in den Projektdateien, Review über Bestätigen-Flag
Der Batch speichert pro Clip die normale Projektdatei; das Review setzt nur `shot.confirmed`.
Dadurch kann jeder Schlag jederzeit im Editor nachkorrigiert werden (Doppelklick im Review), und ein
erneuter Batch-Lauf überschreibt bereits analysierte Clips nicht (außer mit `--reanalyze`, das nur
bestätigte Schläge behält). Export: ein Overlay pro Clip mit allen bestätigten Schlägen. Ein
fehlerhafter Clip bricht die Session nicht ab. Ballposition für den Batch: das Positions-Preset; der
erste Frame mit sichtbar ruhendem Ball wird automatisch gesucht.

## D30 – ruff als Linter
`ruff` (pyflakes, pycodestyle, isort, bugbear) in `requirements-dev.txt`, Konfiguration in
`pyproject.toml`; `B905` (zip strict) ist abgeschaltet, weil fast alle Fälle gleich lange Arrays sind.

## D31 – Packaging: PyInstaller-Ordner-Build mit zwei EXEs, FFmpeg „shared“, Selbsttest
* **Ordner-Build statt One-File:** startet sofort (kein Entpacken bei jedem Start), weniger
  Virenscanner-Fehlalarme, FFmpeg/Modelle liegen sichtbar daneben.
* **Zwei Programme in einem Ordner:** `KPMN Tracer.exe` (GUI, ohne Konsole) und `kpmn-tracer.exe`
  (CLI für Batch/Selbsttest) teilen sich `_internal`.
* **FFmpeg „shared“-Build** (EXEs + gemeinsame DLLs, 193 MB statt 315 MB) wird *nach* PyInstaller
  nach `_internal/ffmpeg` kopiert – als PyInstaller-Daten würden die DLLs analysiert und doppelt
  abgelegt. `imageio_ffmpeg`, Torch und Ultralytics werden ausgeschlossen.
* **Prüfung im Build-Skript:** `kpmn-tracer.exe selftest` (FFmpeg, Testclip erzeugen, Probe, Proxy,
  Rendern, ProRes-Export mit Frameanzahl-Prüfung, Segmentierungsmodell) und
  `KPMN Tracer.exe --smoke-test` (Hauptfenster startet und beendet sich), beides ohne Testmedien.
* Ergebnis: Ordner ≈ 730 MB, ZIP ≈ 320 MB. Größte Posten: FFmpeg, OpenCV-contrib (von MediaPipe
  erzwungen), Qt, MediaPipe.
* Log-Datei und Presets liegen in `~/.kpmn_tracer` (bzw. `$KPMN_HOME`).

## D32 – Erster echter Nutzer-Clip (IMG_2335.MOV): was nicht funktionierte und warum
iPhone 4K-Hochformat, 30 fps, H.264 SDR, Stativ tief hinter dem Abschlag, gelber Range-Ball,
volle Range mit Schlägen aus den Nachbarboxen. Der Ball fliegt fast gerade vom Betrachter weg:
Bildschirmtempo ~240 px im 1. Frame, ~30 px nach 5 Frames, später 3–6 px (Faktor 50–80).
1. **Manueller Tracer hing hinterher:** Das Easing konnte nur ~11:1 (Start-Tempo ≤ 10) –
   physikalisch unmöglich für diesen Schlag (gemessen: ~400 px Rückstand im Steigflug, 4K).
2. **Ton-Impact verworfen:** Mindestabstand 0,6 s zwischen Transienten ließ nur den lauteren
   Nachbarschlag 0,42 s davor übrig → 0,25 s (reicht gegen Echos).
3. **Ball nicht lokalisiert:** Gelb auf grünem Teppich ist in Graustufen kaum sichtbar; zudem gewann
   das kleine, hellere weiße Tee gegen den großen Ball.
4. **Präsenzsignal falsch „anwesend“:** Hinter dem Ball liegt helles, texturiertes Gras – der Kontrast
   blieb nach dem Abflug hoch, die Fusion verwarf daraufhin sogar den richtigen Ton-Treffer.
5. **Steigflug als Ausreißer verworfen:** Der globale Flugmodell-Filter im Tracker passt nicht auf
   diesen nahen Schlag (starkes Abbremsen) und behielt nur den Abstieg.
6. **Absturz** in `presence_signal`, sobald der Ball nicht in Frame 0 markiert ist (GUI-Normalfall).

## D33 – Zeit-Pins („Ball hier“) statt immer extremerer Easing-Kurven
Neues Werkzeug **H**: Klick auf den Ball in einem Frame setzt einen Anker *mit Zeit*. Sobald ein
Anker zwischen Start und Landung eine Zeit hat, folgt das Timing monoton (PCHIP) diesen Punkten statt
dem Easing; Anker ohne Zeit werden dafür nach ihrer aus dem Timing geschätzten Zeit einsortiert.
Ein Klick genau auf die Apex-Markierung versieht den Apex selbst mit einer Zeit. Gemessen am
Nutzer-Clip: Easing (Start-Tempo 10) ~400 px Fehler im Steigflug → 4 Pins 6 px, 8 Pins Ø 9 px über den
ganzen Flug. Zusätzlich Easing-Grenzen erweitert (Start-Tempo bis 100, Abbremsen bis 0,005).
Auto-Tracking ist eine Spezialisierung desselben Mechanismus (alle Anker haben Zeiten).

## D34 – Robustere Ball-Lokalisierung und Präsenzmessung
* Lokalisierung: Top-Hat je Farbkanal (Maximum), mehrere Schwellen, Bewertung mit √Fläche – große,
  gelbe Bälle schlagen kleine, helle Tees/Glanzlichter.
* Präsenz: Im Klick-Frame wird die Farbebene (Grau, B, G, R) gewählt, in der sich der Ball am
  stärksten von der Umgebung abhebt; Score = min(Kontrast im Ballbereich ±2 px,
  Template-Korrelation/0,8). Der Kontrast trennt winzige Bälle, die Korrelation große Bälle vor
  texturiertem Gras (0,99 liegend → 0,25 weg).
* Ein Treffer verlangt ≥ 1 s Abwesenheit (der Schläger beim Ansprechen verdeckt den Ball nur kurz);
  Ton- und Video-Ereignisse werden 1:1 zugeordnet; „Ball blieb liegen“ wird nur direkt nach dem
  Geräusch geprüft.

## D35 – Tracker: lokale statt globaler Ausreißerprüfung
Detektionen werden gegen die Kurve durch ihre zeitlichen Nachbarn geprüft (Startpunkt als fester
Nachbar, Toleranz wächst mit der lokalen Geschwindigkeit); die Nachsuche interpoliert zwischen den
Nachbardetektionen. Das globale Modell dient nur noch der Landeschätzung. Ergebnis beim Nutzer-Clip:
58 Detektionen von Frame 709 (1 Frame nach dem Impact) bis 768 statt nur des Abstiegs.

## D36 – Ballposition eines früheren Clips nur noch auf Wunsch
Gemeldet: „scheinbar werden alte Daten im neuen Video geladen“. Ursache: Beim Speichern wurde die
Ballposition (plus grobe Kurvenform und Flugzeit) als Positions-Preset gemerkt und bei **N** in jeden
neuen Schlag eines *anderen* Clips eingesetzt; der Batch nutzte sie ebenfalls ungefragt. Bei anderem
Standort (z. B. IMG_2366, aus der Hand) lag der Startpunkt neben dem Ball, die Analyse suchte dort und
lieferte Unsinn – oder verwarf den richtigen Ton-Impact („ball did not move“). Zudem lädt ein Clip
immer sein gespeichertes Projekt (auch aus einem Batch-Lauf) ohne Hinweis.
* **N** setzt nur noch die Ballposition *dieses* Clips; *Ballposition vom letzten Clip übernehmen*
  (nur Startpunkt) ist eine explizite Aktion. Batch: Schalter, standardmäßig aus; CLI: `--last-position`.
* Beim Öffnen eines Clips mit gespeichertem Projekt erscheint ein Hinweis; *Projekt zurücksetzen*
  verwirft Schläge, Ballposition und Impact-Kandidaten (Style bleibt, rückgängig machbar).
* Batch: *Bereits analysierte Clips neu berechnen* in der Oberfläche (vorher nur CLI).
* `analyze_clip` legt Ton-Impacts ohne bekannte Ballposition als „Ball markieren“ an, statt mit einem
  Fehler abzubrechen.

## D37 – Steiler, kameranaher Abflug (IMG_2366)
Wedge aus der Hand gefilmt, Ball steigt fast senkrecht: ~430 Proxy-px im ersten Frame, ~70 px im
fünften. Die Startprüfung verlangte 2,5 px Übereinstimmung mit einer 3-Punkt-Hochrechnung und das
Suchfenster endete 0,45 Bilddiagonalen über dem Ball → nur der langsame Schlägerkopf wurde gefunden
(3 Detektionen, Konfidenz 0).
* Zuordnungstoleranz wächst mit der Bildgeschwindigkeit des Modells (2,5 px + 4 %); ein
  Sub-Frame-Fehler des Impact-Zeitpunkts (Schallverzögerung, Rolling Shutter) verschiebt den Ball
  direkt nach dem Abflug um Dutzende Pixel.
* Hypothesen werden auf ihrer ganzen Unterstützung neu angepasst und erneut zugeordnet, bis sie
  stabil sind – so erreicht eine Hypothese aus drei Frames auch die stark abgebremsten späteren.
* Suchfenster: alles oberhalb des Startpunkts.
* Glattheit einer Hypothese relativ zur lokalen Geschwindigkeit (sonst gewinnt der langsame,
  „glatte“ Schlägerkopf gegen den schnellen Ball).
Ergebnis: 55 Detektionen von Frame 13 bis 108 (Abflug, Apex in den Wolken, Abstieg vor den Bäumen),
Konfidenz 0,76; IMG_2335 (0,98) und der CC0-Referenzclip (0,91) unverändert.

## D38 – Einzelbild-Export aus dem Original
Für Bild-Beiträge wird der Frame aus dem **Original** dekodiert (volle Auflösung, Rotation, HDR→SDR
wie der eingebrannte Export), nicht aus dem 1080p-Proxy. Frame *i* der Timeline → Zeitstempel des
*i*-ten Quell-Frames (VFR-Modus „frames“) bzw. des zur Zeit *i/fps* gezeigten Frames („resample“);
FFmpeg sucht genau (`-ss` vor `-i` mit Dekodierung) eine Viertel-Frame-Dauer vor diesem Zeitpunkt.
Getestet mit Index-Videos (CFR, VFR mit verschobenen Zeitstempeln, gedreht). ~4 s pro 4K-Frame.

## D39 – Scorecard Studio als eigenständige HTML-Seite mit Designs als Daten
Der vom Nutzer mitgebrachte Generator (Canvas-Rendering, eine Datei) bleibt eine HTML-Seite und
wird von der App im Standard-Browser geöffnet (*Extras*, CLI `scorecard`), statt ihn nach Qt zu
portieren oder QtWebEngine (+~150 MB) einzubinden: getrennt vom Tracer, ohne App nutzbar, als
statische Seite hostbar.
* Alles Markenspezifische wurde aus dem Code in **Designs** verschoben (`themes.js`): Farben (6
  Grundfarben, Rest abgeleitet über Kontrast/Mischung), Schriftpaar, Hintergrund (Fairway+Tracer,
  Mähstreifen, schlicht), Logo (Data-URL, rund/eckig), Marke und Handle. Halbtransparente Flächen
  werden aus der Textfarbe abgeleitet, damit helle Designs funktionieren.
* *NightRange · teeoff.kpmn* ist das ursprüngliche Design (Farben, Schrift, Marke; das Kanal-Logo
  wurde vor der Veröffentlichung entfernt, D42) und bleibt Vorlage; vier
  neutrale Vorlagen ohne Marke. Änderungen an einer Vorlage erzeugen automatisch ein eigenes Design
  (Browser-Speicher), Export/Import als JSON.
* Logos liegen als Data-URL im Design, weil Bilder von `file://` den Canvas für den PNG-Export
  sperren würden; hochgeladene Logos werden auf 480 px verkleinert.

## D40 – Einführungstour als Overlay im Hauptfenster
Wunsch: Die App ist ohne Erklärung schwer zu durchschauen. Statt eines separaten Assistenten
(der vom echten Fenster ablenkt) dunkelt ein Overlay das Hauptfenster ab, hebt den jeweils
erklärten Bereich hervor und zeigt daneben eine Sprechblase (13 Schritte: Ablauf, Vorschau,
Zeitleiste, Transport, Schläge, Automatik, Werkzeuge, Kamera, Flugkurve, Aussehen, Text, Export,
Menüs). Ziele werden zur Laufzeit als Widgets bestimmt; Bereiche im scrollbaren Seitenpanel
werden vorher ins Bild gescrollt; die Sprechblase geht auf die Seite mit dem meisten Platz.
Läuft automatisch einmal beim ersten Start (`settings.json` → `extra.tour_done`), danach über
*Hilfe › Einführungstour*. Während der Tour sind Klicks ins Fenster gesperrt.

## D41 – macOS und Linux
Wunsch vor der Veröffentlichung: neben Windows auch Mac (wichtigstes Ziel) und Linux.
Der Code war bis auf Kleinigkeiten plattformneutral (Python/Qt/OpenCV/MediaPipe/FFmpeg); die Arbeit
lag in Build, Abhängigkeiten und Laufzeit-Details. Da nur ein Windows-Rechner vorhanden ist, laufen
Tests und Builds für alle Systeme auf echten Maschinen in **GitHub Actions** (`build.yml`):
Windows x64, macOS arm64 (macos-14), macOS x64 (macos-15-intel), Linux x64 (Ubuntu 22.04 – ältere
glibc, damit der Build auch auf älteren Distributionen läuft). Jeder Build führt die komplette
Testsuite, den Selbsttest des fertigen Pakets und einen GUI-Starttest aus.
* **FFmpeg:** macOS/Linux nutzen statische Release-Builds (FFmpeg 9.0.2, Martin Riedl, per URL
  gepinnt, SHA-256 geprüft); Windows unverändert BtbN. Der Selbsttest prüft jetzt die benötigten
  Funktionen (prores_ks, libx264/265, zscale, tonemap).
* **Pakete:** macOS als `.app` im `.dmg` (CLI unter `Contents/MacOS/kpmn-tracer`, Videos per Finder
  „Öffnen mit“), Linux als `tar.gz` mit `install.sh` (Menüeintrag + `kpmn-tracer` im PATH, ohne root).
* **Nicht signiert/notarisiert:** Apple-Notarisierung und Windows-Codesignatur kosten Geld; die
  Anleitungen erklären den einmaligen „Trotzdem öffnen“-Schritt. Nachrüstbar, ohne den Build zu ändern.
* **Intel-Macs:** MediaPipe veröffentlicht für x86_64-macOS nur noch Versionen ≤ 0.10.21 (mit
  numpy 1.x, OpenCV < 4.12); Abhängigkeiten per Umgebungsmarker getrennt, alle Tests grün. Das
  mitgezogene JAX wird nicht gebündelt.
* **Linux:** MediaPipe braucht die System-Bibliothek `libGLESv2` (Paket `libgles2`). Fehlt sie,
  meldet die App das klar und arbeitet ohne Personen-Maske weiter (vorher: Fehlerdialog, Abbruch).
* **Kleinigkeiten:** Tastenkürzel-Texte mit ⌘ auf dem Mac, Einstellungen/Beenden im App-Menü,
  Standardschrift je System, Tests blockieren nie an modalen Dialogen, Test-Timeouts in CI.

## D42 – Veröffentlichung als Open Source (GPL-3.0)
* Lizenz **GPL-3.0-or-later**: passt zum mitgelieferten GPL-FFmpeg (x264/x265, `--enable-version3`)
  und hält Weiterentwicklungen offen.
* Vor dem Öffentlichmachen wurde die **komplette Git-Geschichte** bereinigt: das Kanal-Logo aus der
  NightRange-Vorlage entfernt und die private Autor-E-Mail durch die anonyme GitHub-Adresse ersetzt.
  Releases, deren Downloads das Logo enthielten (0.2.0–0.3.0), wurden gelöscht und durch 0.3.1
  ersetzt; alte Build-Artefakte und Workflow-Läufe wurden entfernt.

## D43 – Lange Sessions in 4K/120 fps HDR (IMG_2367.MOV, 11,6 min, 83.845 Frames)
Vorher: Laden ~2,7 h, Schlag-Erkennung hing 28 min bei „17 %" und fand **0 Schläge**, jeder Schlag
danach ~8 min Analyse. Ursachen und Lösungen:
* **Analyse-Kopie (Proxy):** Software-HEVC-Dekodierung (~35 fps) und Float-Tonemapping jedes 4K-Frames
  (~9 fps). Auf NVIDIA-Karten jetzt CUDA-Dekodierung + -Skalierung und Tonemapping mit libplacebo
  (Vulkan) mit fester Kurve (`gamma`, ohne Peak-Erkennung: `tonemap_opencl` passt die Helligkeit
  laufend an die Szene an); nur die kleinen Proxy-Frames gehen zur CPU – ~120 statt 8,7 fps.
  Rotation explizit (`-noautorotate` + `transpose`). Fällt die GPU-Kette aus (anderer Grafikchip,
  falsche Frame-Zahl), wird automatisch die CPU-Kette genommen, die jetzt *vor* dem Tonemapping
  skaliert (2× schneller). Frame-Zählung über Pakete statt Dekodieren (18 s statt 14 min).
  Die MJPEG-Qualität bleibt bei 2: schon Stufe 3 kostet bei schwachen Bällen Genauigkeit (Tests
  `faint_ball`, `handheld_vanishes`), dafür ist der Proxy groß (dieser Clip: ~36 GB).
* **Schlag-Erkennung:** Die Bild-Erkennung beobachtete *eine* Stelle (wo der Ball beim Klick lag).
  In einer echten Session wird an mehreren Stellen aufgeteet, die Stelle war fast immer leer → alle
  245 Geräusche (Nachbarboxen!) galten als „fremd". Neu: Für jedes Geräusch werden vier Frames
  (−0,3/−0,1 s, +0,2/+0,3 s) angesehen – verschwindet in der Schlagzone (8 % der Bildgröße um den
  geklickten Ball) ein ruhender, heller, ballgroßer Fleck, ist es ein eigener Schlag, und der Fleck
  ist zugleich der Startpunkt dieses Schlags. 245 Geräusche in ~27 s; alle 23 Schläge gefunden (an
  drei Tee-Positionen), Nachbarboxen, Probeschwünge, Schuhspitzen und Hände verworfen; ein leiser
  Fehltreffer bleibt übrig und fällt durch die Ballverfolgung (kein Flug → niedrige Konfidenz).
  Farbe hilft nicht (driftet mit dem Licht über die Session). Das Frame-für-Frame-Abtasten und die
  Abflug-Prüfung (`launch_seen`, einmal 17 min für *einen* Kandidaten) laufen nur noch bei Clips bis
  2 min oder ohne Ton.
* **Pro Schlag:** Ballverfolgung: Zuordnung vektorisiert, kurze Vorwärtssprünge im Proxy werden
  durchgelesen statt gesucht (ein Suchen kostet ~10 dekodierte Frames), Personenmasken pro Frame
  gecacht – Ergebnis bit-gleich, ~8 → ~3–5 min pro Schlag bei 4K/120 fps.
* **Bewusst nicht übernommen** (getestet, kosteten Genauigkeit bei schwachen Bällen): großzügigere
  Stativ-Erkennung (das Handy am Boden vibriert um bis zu 0,9 px, wenn jemand vorbeigeht – das
  Ausgleichen hilft der Ballerkennung messbar), Personenmasken in gleicher Zeitrate (jeder 4./8.
  statt jeder 2. Frame bei 120 fps) und eine stärkere JPEG-Kompression des Proxys.
* **Offen:** Mehrere Schläge parallel analysieren (OpenCV gibt den GIL frei) – braucht getrennte
  Reader/Masken-Caches je Schlag.
