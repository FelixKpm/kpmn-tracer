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
