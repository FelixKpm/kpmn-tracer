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
