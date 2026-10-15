# KPMN Tracer

Windows-Desktop-App, die Golf-Videos von der Driving Range (iPhone, Stativ oder aus der Hand) mit
einem TV-ähnlichen Ball-Tracer versieht. Der Tracer wird als **Overlay mit Alpha-Kanal** exportiert
und in DaVinci Resolve frame-genau über den Originalclip gelegt – das Original wird nie verändert.

* Ball wird automatisch erkannt und verfolgt (oder mit wenigen Klicks gesetzt/korrigiert)
* Kamerawackeln wird kompensiert – der Tracer „klebt“ in der Welt
* Tracer kann hinter dem Golfer verlaufen (Personen-Maske)
* Schlagmomente werden über Ton und Video automatisch gefunden
* Batch-Verarbeitung einer ganzen Range-Session mit Review-Liste

Status und technische Details: [PROGRESS.md](PROGRESS.md), [DECISIONS.md](DECISIONS.md).

---

## Installation

### Fertiger Build (empfohlen)
1. `KPMN-Tracer-<version>-win64.zip` entpacken (z. B. nach `C:\Programme\KPMN-Tracer`).
2. `KPMN Tracer.exe` starten. FFmpeg und die Modelle sind enthalten, es muss nichts installiert werden.
3. Optional prüfen: `kpmn-tracer.exe selftest` in einer Eingabeaufforderung im selben Ordner.

Beim allerersten Start kann der Virenscanner die mitgelieferten Programme einige Sekunden prüfen.

### Aus dem Quellcode (Entwicklung)
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python tools\fetch_ffmpeg.py    # ffmpeg + ffprobe nach vendor\ffmpeg
.venv\Scripts\python tools\fetch_models.py    # MediaPipe-Modelle nach vendor\models
.venv\Scripts\python -m kpmn_tracer            # GUI
.venv\Scripts\python -m pytest                 # Tests
.venv\Scripts\python tools\build_windows.py    # Build -> dist\KPMN-Tracer + ZIP
```

---

## Bedienung

### 1. Clip öffnen
`Strg+O` oder Datei ins Fenster ziehen. Beim ersten Öffnen wird eine Vorschau-Kopie (Proxy) erstellt;
die Statusleiste zeigt Auflösung, fps, Rotation, **VFR** und **HDR** an.

### 2a. Automatisch (empfohlen)
1. Zu einem Frame gehen, in dem der Ball ruhig liegt, **N** (neuer Schlag) drücken und auf den Ball
   klicken.
2. **B** – *Ball tracken*: Personen-Maske, Kamerabewegung und Ballflug werden analysiert.
   Oder *Ganzen Clip analysieren*: alle Schläge im Clip werden gefunden und getrackt.
3. Ergebnis prüfen (Leertaste = abspielen). Bei geringer Konfidenz sind Start, Apex und Landung
   vorbefüllt – einfach die Punkte an die richtige Stelle ziehen.

### 2b. Manuell
1. Zum Schlagmoment scrubben (←/→, Shift = 10 Frames), **N** drücken.
2. Auf den Ball klicken (Start), dann auf den höchsten Punkt (Apex), dann auf den Landepunkt.
3. Zum Landezeitpunkt gehen und **O** drücken (oder die Flugzeit im Panel einstellen).
4. Form und Tempo im Panel *Flugkurve* anpassen; **P** fügt einen Zusatzpunkt hinzu (Draw/Fade).
5. **H – Ball hier:** Hängt der Tracer hinter dem Ball her (typisch, wenn der Ball vom Betrachter
   wegfliegt), in einigen Frames auf den Ball klicken – der Tracer-Kopf ist in diesen Frames genau
   dort. 2–3 Klicks direkt nach dem Impact, einer am Apex und ein, zwei im Abstieg reichen.

### 3. Nachkorrigieren (aus der Hand gefilmt)
* **T** – *Kamera tracken*: unsichere Frames erscheinen **rot** in der Timeline.
* **K** – *Korrektur*: in einem problematischen Frame dorthin klicken, wo der Tracer-Kopf sein soll.
  Die Korrektur wird zwischen den Nachbar-Frames weich interpoliert.

### 4. Aussehen
Style-Panel: Farbe, Dicke, Verjüngung, Glow, weißer Kern, Schatten, „voller Pfad“ oder „Schweif“,
Stehenbleiben und Ausblenden nach der Landung. Eigene Styles als **Preset** speichern.
*Tracer hinter Golfer* schneidet den Tracer dort aus, wo der Golfer ist.
*Text-Einblendung*: z. B. „7-Eisen · 145 m“, animiert am Apex, am Landepunkt oder in einer Ecke.

### 5. Exportieren (`Strg+E`)
| Format | Wofür |
|---|---|
| **ProRes 4444 mit Alpha (.mov)** | Overlay für DaVinci Resolve (Standard) |
| PNG-Sequenz mit Alpha | Alternative für jedes Schnittprogramm |
| H.264 / H.265 eingebrannt (.mp4) | Direkt posten (Original + Tracer, mit Ton, SDR) |

Das Overlay hat immer dieselbe Auflösung, dieselbe Bildrate und **dieselbe Frameanzahl** wie der Clip.

### 6. Range-Session im Batch (`Strg+B`)
1. Einmal einen Schlag im Editor setzen und speichern – die Ballposition am Stativplatz wird als
   **Positions-Preset** gemerkt.
2. Batch-Fenster: Ordner wählen → *Analysieren*. Jeder Schlag erscheint als Bild mit Tracer und
   Konfidenz.
3. Häkchen setzen (oder *Alle darüber bestätigen*), unsichere per Doppelklick im Editor korrigieren.
4. *Bestätigte exportieren* – ein Overlay pro Clip.

### Tastenkürzel (Übersicht mit **F1**)
| Taste | Aktion |
|---|---|
| ← / → (Shift: ±10) | Frame zurück / vor |
| Leertaste | Abspielen / Pause |
| Pos1 / Strg+← / Strg+→ | Zum Impact / vorheriger, nächster Schlag |
| N · I · O | Neuer Schlag · Impact = Frame · Landung = Frame |
| V S A L P K H | Auswählen, Start, Apex, Landung, Zusatzpunkt, Korrektur, Ball hier |
| B · T · D | Ball tracken · Kamera tracken · Impacts erkennen |
| C | Schlag bestätigen |
| Entf | Ausgewählten Zusatzpunkt löschen |
| Strg+Z / Strg+Y | Rückgängig / Wiederholen |
| Strg+S · Strg+E · Strg+B | Speichern · Exportieren · Batch |
| Mausrad / rechte Taste ziehen / F | Zoom / Verschieben / Einpassen |

---

## Empfohlener Workflow in DaVinci Resolve

1. Originalclip auf **V1** legen.
2. Das exportierte Overlay `<clip>_tracer.mov` auf **V2** direkt darüber legen, mit demselben
   Startpunkt – beide sind exakt gleich lang.
3. Inspector des Overlays: **Composite Mode „Normal“**, Deckkraft 100 %. Der Alpha-Kanal wird
   automatisch erkannt (falls nicht: Clip-Attribute → Alpha-Modus „Straight“).
4. Hochformat-Clips: Timeline in 1080×1920 anlegen – das Overlay ist bereits in
   Anzeige-Orientierung (Rotation angewendet).
5. Mehrere Schläge eines Clips sind in einem Overlay enthalten.

PNG-Sequenz statt ProRes: Ordner in den Media Pool ziehen, Resolve erkennt die Sequenz als Clip.

---

## Troubleshooting

**Overlay läuft in Resolve aus dem Takt (VFR)**
iPhone-Videos haben oft eine variable Bildrate. KPMN Tracer zeigt das in der Statusleiste an
(„VFR → … Frames @ 30 fps“) und legt jeden Quell-Frame 1:1 auf einen Overlay-Frame – genau so, wie
Resolve VFR-Clips abspielt. Prüfen: Clip und Overlay müssen in Resolve gleich lang sein und bündig
beginnen. Wurde der Clip vorher in eine CFR-Datei umgewandelt, unter *Einstellungen* → „VFR-Clips“
*Zeitbasiert neu abtasten* wählen und den Clip neu öffnen.

**Farben sehen in der Vorschau flau/anders aus (HDR / Dolby Vision)**
Für Analyse und Vorschau wird HDR (HLG/PQ) auf SDR heruntergerechnet; das Original bleibt
unverändert und das Alpha-Overlay ist farbneutral (BT.709). In Resolve wie gewohnt mit dem
HDR-Original graden. Nur die *eingebrannten* MP4-Exporte sind SDR (zum Posten gedacht).

**Ball wird nicht gefunden / Tracking ist falsch**
* Im Impact-Frame genau auf den Ball klicken (vorher mit dem Mausrad hineinzoomen).
* Impact-Frame prüfen: der *letzte* Frame, in dem der Ball noch ruhig liegt (**I** setzt ihn).
* Dunkle Clips, Gegenlicht oder Ball vor gleich hellem Hintergrund: die Konfidenz ist niedrig, die
  Punkte sind vorbefüllt – einfach ziehen (manueller Modus). *Vereinfachen* macht aus einem
  Auto-Ergebnis drei gut ziehbare Punkte.
* Stark bewegte Kamera: **T** (Kamera tracken), rot markierte Frames mit **K** korrigieren.

**Tracer hängt im Steigflug hinter dem Ball her (manueller Modus)**
Bei Bällen, die vom Betrachter wegfliegen, ist der Ball im ersten Frame nach dem Impact schon weit
oben und wird danach im Bild immer langsamer. Am besten **B** (Ball tracken) verwenden; von Hand mit
dem Werkzeug **H** in 2–3 Frames direkt nach dem Impact auf den Ball klicken.

**Impacts werden nicht erkannt**
Der Ton ist die zuverlässigste Quelle. Ohne Ton (oder in Zeitlupe) muss der Ball vorher sichtbar
ruhig an der markierten Stelle liegen. Sonst den Schlag von Hand anlegen (**N** am Schlagmoment).

**„ffmpeg/ffprobe not found“** (nur Quellcode-Variante): `python tools\fetch_ffmpeg.py` ausführen
oder `KPMN_FFMPEG_DIR` auf einen Ordner mit ffmpeg.exe/ffprobe.exe setzen.

**Personen-Maske fehlt** (nur Quellcode-Variante): `python tools\fetch_models.py`.

**Log-Datei** für Fehlerberichte: `%USERPROFILE%\.kpmn_tracer\kpmn_tracer.log`.

---

## Kommandozeile

```powershell
kpmn-tracer.exe selftest                                   # Installation prüfen
kpmn-tracer.exe probe clip.mov                             # Metadaten (Rotation, VFR, HDR …)
kpmn-tracer.exe analyze clip.mov --ball 960 1500           # alle Schläge finden + tracken
kpmn-tracer.exe export clip.mov --format prores            # Overlay aus clip.mov.kpmntrace.json
kpmn-tracer.exe batch D:\Range\Session --auto-confirm 0.8 --export prores
kpmn-tracer.exe batch-export D:\Range\Session
```
Aus dem Quellcode: `python -m kpmn_tracer …`.

## Dateien

| Datei / Ordner | Inhalt |
|---|---|
| `<clip>.kpmntrace.json` | Projekt: Schläge, Punkte, Kamerapfad, Korrekturen, Style – nachbearbeitbar ohne Neuberechnung |
| `.kpmn_cache\` (neben dem Clip) | Vorschau-Proxy, Personen-Masken, Audio – kann jederzeit gelöscht werden |
| `kpmn_review\` | Thumbnails des Batch-Reviews |
| `%USERPROFILE%\.kpmn_tracer\` | Style-Presets, Positions-Preset, Einstellungen, Log |

## Optionale ML-Ballerkennung
Nur nötig, wenn die klassische Erkennung bei eigenen Clips nicht reicht (DECISIONS.md, D26):
`pip install -r requirements-ml.txt`, Trainingsdaten mit `tools/make_ball_dataset.py` aus eigenen
analysierten Clips erzeugen, mit `tools/label_balls.py` prüfen, mit `tools/train_yolo.py` trainieren,
Modell in den Einstellungen wählen. Ultralytics steht unter AGPL-3.0 und ist nicht im Build enthalten.

## Lizenzen von Drittkomponenten
FFmpeg (GPL-Build, Lizenztext in `_internal\ffmpeg\LICENSE.txt`), Qt/PySide6 (LGPL), OpenCV
(Apache 2.0), MediaPipe und Modelle (Apache 2.0), NumPy/SciPy (BSD).
