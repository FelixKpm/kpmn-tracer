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
