# KPMN Tracer – Projektauftrag für Claude Code

Du baust eine Windows-Desktop-App, die Golf-Videos (Driving Range, iPhone-Aufnahmen) automatisch mit einem TV-ähnlichen Ball-Tracer versieht. Arbeite die Phasen unten der Reihe nach selbstständig ab. Es gibt keine Deadline – Qualität und Robustheit gehen vor Geschwindigkeit.

---

## 0. Arbeitsweise

- Arbeite **autonom** Phase für Phase. Frag nur nach, wenn eine Entscheidung wirklich nicht rückgängig zu machen ist.
- Lege im Repo-Root an und halte aktuell:
  - `PROGRESS.md` – welche Phase fertig ist, was offen ist, bekannte Probleme
  - `DECISIONS.md` – kurze Begründung für jede Architektur- oder Library-Entscheidung
- **Commit nach jedem abgeschlossenen Schritt** mit aussagekräftiger Message.
- Jede Phase hat **Abnahmekriterien**. Eine Phase gilt erst als fertig, wenn diese erfüllt sind und die Tests grün sind.
- Schreib Unit-Tests (pytest) für alle Mathe-/Logik-Teile (Kurven, Homographie, Timing, Export-Parameter).
- Erzeuge für Tests **synthetische Videos** (z. B. weißer Punkt, der auf Parabel über einen Hintergrund fliegt, optional mit simuliertem Kamerawackeln), damit Tracking messbar getestet werden kann, ohne echte Aufnahmen.
- Code-Stil: Typ-Hints, kleine Module, keine Gott-Klassen. Logging statt print.

---

## 1. Rahmenbedingungen

| Punkt | Vorgabe |
|---|---|
| Zielsystem | Windows 10/11, x64 |
| Sprache | Python 3.11+ |
| GUI | PySide6 |
| Video/CV | OpenCV (`opencv-python`), NumPy, SciPy |
| Personen-Segmentierung | MediaPipe (Selfie/Person Segmentation) |
| Ballerkennung (optional ML) | Ultralytics YOLO (nur in Phase 6, als austauschbares Modul) |
| Encoding | FFmpeg (über `imageio-ffmpeg` mitliefern oder System-FFmpeg prüfen) |
| Packaging | PyInstaller → eine startbare `.exe` / Ordner-Build |
| Schnittprogramm des Nutzers | DaVinci Resolve (Overlay wird dort über den Clip gelegt) |

### Eingangsmaterial (wichtig!)
- iPhone-Videos: HEVC (H.265), oft **10-bit HDR (HLG / Dolby Vision)**, oft **variable Framerate (VFR)**, 30/60/120/240 fps (Slow-Mo).
- Sowohl **Stativ** als auch **Handheld** (Wackeln, leichtes Schwenken, Zoom).
- Hochformat (9:16) und Querformat.

Behandle das sauber:
- Beim Import Metadaten mit `ffprobe` auslesen (Auflösung, Rotation, fps, VFR ja/nein, Farbraum, Bit-Tiefe).
- Bei VFR: intern auf konstante Framerate normalisieren und dem Nutzer anzeigen, damit das Overlay in Resolve frame-genau passt.
- Rotation-Metadaten korrekt anwenden (Hochformat!).
- HDR: Für die Analyse auf 8-bit SDR herunterrechnen, aber das Original nie verändern.

---

## 2. Projektstruktur (Vorschlag, darf begründet abweichen)

```
kpmn-tracer/
├─ kpmn_tracer/
│  ├─ io/            # Import, ffprobe, Frame-Reader, Export
│  ├─ camera/        # Feature-Tracking, Homographie, Kamerapfad
│  ├─ ball/          # Impact-Erkennung, Ballerkennung, Trajektorien-Fit
│  ├─ segmentation/  # Personen-Maske
│  ├─ render/        # Tracer-Zeichnung, Styles, Glow, Okklusion
│  ├─ project/       # Projektdatei (JSON), Presets
│  ├─ gui/           # PySide6 UI
│  └─ cli.py         # Batch-/Kommandozeilen-Modus
├─ tests/
├─ tools/            # Generator für synthetische Testvideos
├─ PROGRESS.md
├─ DECISIONS.md
└─ README.md
```

Jeder Clip bekommt eine **Projektdatei** (`<clip>.kpmntrace.json`) mit allen Punkten, Keyframes, Kamerapfad und Style, damit man später ohne Neuberechnung nachbessern kann.

---

## 3. Phasen

### Phase 1 – Fundament: Import, Vorschau, manueller Tracer, Export

**Ziel:** Stativ-Clip laden, Tracer von Hand setzen, transparent exportieren.

1. Projekt-Setup (venv, `requirements.txt`, pytest, Logging).
2. Import mit ffprobe-Analyse (siehe Abschnitt 1), Frame-Reader mit Seek.
3. Minimal-GUI: Video-Vorschau, Timeline/Scrubber, Frame-Schritt vor/zurück.
4. Manueller Modus: Nutzer markiert **Impact-Frame**, **Startpunkt (Ball)**, **Apex**, **Landepunkt** (+ optional Landeframe).
5. Kurvenmodell:
   - Quadratische/kubische Bezier durch die Punkte, optional seitliche Krümmung (Draw/Fade) über einen zusätzlichen Kontrollpunkt.
   - **Zeitverlauf realistisch**: Ball schnell nach Impact, langsamer Richtung Apex, dann wieder etwas schneller (Easing-Kurve, parametrisierbar).
6. Renderer:
   - Linie mit wählbarer Farbe, Dicke, Verjüngung zum Ballende hin, **Glow**, optional Schatten.
   - Modi: "voller Pfad bleibt stehen" und "kurzer Schweif".
   - Ausblenden nach Landung (Fade-out-Dauer einstellbar).
7. Export:
   - **Overlay mit Alpha-Kanal** als ProRes 4444 (`-c:v prores_ks -profile:v 4 -pix_fmt yuva444p10le`) **und** alternativ PNG-Sequenz.
   - Gleiche Auflösung, Framerate und Länge wie der Quell-Clip (frame-genau!).
   - Zusätzlich optional "eingebrannter" Export (H.264/H.265 MP4) zum direkten Posten.
8. Projektdatei speichern/laden.

**Abnahme:** Synthetisches Stativ-Video → Overlay-Export → per Skript wieder über das Original gelegt ergibt einen sauber sitzenden Tracer. Frameanzahl Overlay == Frameanzahl Original. Tests grün.

---

### Phase 2 – Handheld: Kamerabewegung kompensieren

**Ziel:** Tracer klebt in der Welt, nicht am Bildschirm.

1. Feature-Tracking: `goodFeaturesToTrack` + `calcOpticalFlowPyrLK`, Features regelmäßig nachfüllen.
2. Pro Frame **Homographie zum Referenz-Frame** (= Impact-Frame) via `findHomography` mit RANSAC. Für große Distanzen Frame-zu-Frame-Homographien verketten und gegen Drift regelmäßig direkt gegen den Referenz-Frame neu registrieren.
3. Glättung des Kamerapfads (z. B. Kalman oder gleitender Mittelwert auf den Homographie-Parametern), Ausreißer verwerfen.
4. Tracer wird im Referenz-Frame definiert und pro Frame mit der inversen Transformation ins aktuelle Bild projiziert.
5. Qualitätsanzeige: Pro Frame ein Konfidenzwert (Inlier-Anteil). Frames mit schlechtem Tracking in der Timeline rot markieren.
6. **Manueller Korrekturmodus:** Nutzer kann in problematischen Frames die Position des Tracers per Keyframe verschieben; dazwischen wird interpoliert.
7. Automatische Erkennung Stativ vs. Handheld (Bewegung unter Schwellwert → Stativmodus, Tracking überspringen).

**Abnahme:** Synthetisches Video mit simuliertem Wackeln/Zoom → mittlerer Positionsfehler des Tracers ≤ 2 px gegenüber Ground Truth. Tests grün.

---

### Phase 3 – Personen-Maske

**Ziel:** Golfer stört das Kamera-Tracking nicht, Tracer kann hinter dem Golfer verlaufen.

1. Personen-Segmentierung pro Frame mit MediaPipe (ggf. nur jeden n-ten Frame + Interpolation für Speed).
2. Feature-Punkte innerhalb der Personenmaske für das Kamera-Tracking ignorieren.
3. **Okklusion:** Option "Tracer hinter Golfer" – Tracer wird dort ausgeschnitten, wo die Personenmaske liegt (Kanten weich).
4. Maske im Projekt cachen.

**Abnahme:** Kamera-Tracking-Fehler wird mit Maske messbar besser als ohne (Test mit synthetischer "Person", die sich bewegt). Okklusion sichtbar korrekt in Vorschau und Export.

---

### Phase 4 – Automatische Impact-Erkennung

**Ziel:** Der Nutzer muss den Schlagmoment nicht mehr suchen.

1. **Audio:** Transienten-Erkennung im Audiospur (kurzer, lauter Peak = Schlaggeräusch). Kandidaten-Zeitpunkte liefern.
2. **Video:** Ball-Startpunkt vom Nutzer einmal anklicken (oder aus Preset übernehmen). Impact = erster Frame, in dem sich die Region um den Ball stark verändert (Frame-Differenz).
3. Beide Signale kombinieren, bei mehreren Schlägen in einem Clip **alle** Impacts finden (Range-Session mit mehreren Bällen!).
4. Ergebnis in der Timeline als Marker, Nutzer kann bestätigen/verschieben.

**Abnahme:** Auf synthetischen Clips mit Audio-Klick wird der Impact auf ±1 Frame genau gefunden. Mehrere Schläge in einem Clip werden einzeln erkannt.

---

### Phase 5 – Automatisches Ball-Tracking (klassisch, ohne ML)

**Ziel:** Ballflug wird automatisch verfolgt, der Nutzer prüft nur noch.

Rahmen: Golfball ist nach wenigen Frames winzig (wenige Pixel), oft kaum sichtbar vor Himmel. Deshalb **physikalisch geführtes Tracking** statt naiver Objekterkennung.

1. Arbeite in **kamerakompensierten Koordinaten** (Phase 2), sonst erzeugt das Wackeln Fehldetektionen.
2. Kandidatenerkennung pro Frame:
   - Differenz zum stabilisierten Vorframe / Hintergrundmodell
   - Kleine, helle, kompakte Blobs (Größe, Helligkeit, Rundheit filtern)
   - Personenmaske ausschließen
3. Verfolgung: Kalman-Filter mit Bewegungsmodell (Startgeschwindigkeit hoch, Gravitation nach unten im Bild, leichte Seitenkrümmung erlaubt). Suchfenster um die Vorhersage, Größe wächst bei verpassten Frames.
4. **Lücken überbrücken:** Wenn der Ball einige Frames verloren geht, weiter vorhersagen statt abbrechen.
5. **Trajektorien-Fit:** Auf alle gefundenen Punkte eine glatte Flugkurve fitten (robust, z. B. RANSAC auf ein parabelähnliches Modell + seitliche Krümmung). Wenn der Ball irgendwann unsichtbar wird, den Rest aus dem Fit extrapolieren bis zur Landung bzw. zum Ausblenden.
6. Konfidenz pro Schlag ausgeben. Unter Schwellwert → automatisch in den manuellen Modus aus Phase 1 mit vorbefüllten Punkten (Start, geschätzter Apex, geschätzte Landung), damit der Nutzer nur noch korrigiert.
7. Ergebnis wird immer in die gleichen editierbaren Punkte/Keyframes überführt wie beim manuellen Modus – **eine** Datenstruktur für beides.

**Abnahme:** Auf synthetischen Clips (Stativ und Handheld, Ball mit wenigen Pixeln, Ball verschwindet zeitweise) wird die Flugbahn mit mittlerem Fehler ≤ 3 px rekonstruiert. Auf echten Clips: Ergebnis ist mindestens ein brauchbarer Startpunkt zum Nachkorrigieren.

---

### Phase 6 – Optional: ML-Ballerkennung

Nur angehen, wenn Phase 5 auf echten Clips nicht reicht.

1. Austauschbares Detector-Interface, sodass klassische und ML-Erkennung parallel existieren.
2. YOLO (Ultralytics) für kleine Objekte; prüfen, ob es öffentlich verfügbare Golfball-Datensätze mit passender Lizenz gibt, und die Lizenz in `DECISIONS.md` dokumentieren.
3. Tool zum Labeln eigener Frames aus den Clips des Nutzers (damit er später mit eigenen Range-Videos nachtrainieren kann).
4. Ausgabe der Detektionen fließt in denselben Kalman/Fit-Prozess wie in Phase 5.
5. Inferenz muss auf einem normalen Windows-PC ohne CUDA laufen (CPU-Fallback), GPU optional.

---

### Phase 7 – Workflow & Komfort

1. **Batch-Modus** (GUI und CLI): Ordner wählen → alle Clips analysieren → Review-Liste, in der jeder Schlag als Thumbnail mit Konfidenz erscheint → Export aller bestätigten Clips.
2. **Presets:** Tracer-Styles speichern/laden (Farbe, Dicke, Glow, Schweif, Fade).
3. **Positions-Preset für Stativplatz:** Letzten Ball-Startpunkt und grobe Kurvenform übernehmen.
4. Optionale Text-Overlays über dem Tracer (z. B. Schläger, Carry-Distanz – manuell eingegeben), animiert eingeblendet. Auch mit Alpha exportierbar.
5. Tastenkürzel für alle häufigen Aktionen (Frame vor/zurück, Punkt setzen, Play, Export).
6. Fortschrittsanzeige und Abbrechen bei langen Analysen; Analyse im Hintergrund-Thread, GUI blockiert nie.

---

### Phase 8 – Packaging & Doku

1. PyInstaller-Build für Windows, FFmpeg wird mitgeliefert, Modelle (MediaPipe/YOLO) liegen im Build.
2. `README.md`: Installation, Bedienung, empfohlener Resolve-Workflow (Overlay auf Spur über dem Clip legen, Composite-Modus "Normal").
3. Kurze Troubleshooting-Sektion (VFR, HDR-Farben, Tracking schlägt fehl → manueller Modus).

---

## 4. Nicht-Ziele (vorerst)

- Kein Live-Tracking während der Aufnahme
- Kein 3D-Kurskarten-Overlay
- Keine Cloud-Funktionen, alles läuft lokal
- Keine Mac/Linux-Builds (Code aber nicht unnötig Windows-spezifisch schreiben)

---

## 5. Definition of Done (Gesamtprojekt)

- Stativ- und Handheld-Clip vom iPhone lassen sich importieren, der Ball wird automatisch getrackt oder mit wenigen Klicks korrigiert.
- Overlay-Export mit Alpha liegt in DaVinci Resolve frame-genau über dem Original.
- Batch-Verarbeitung einer ganzen Range-Session funktioniert.
- Alle Tests grün, `PROGRESS.md` zeigt alle Phasen als erledigt, `README.md` erklärt die Nutzung.
