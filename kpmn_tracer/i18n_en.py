"""English UI texts, keyed by the German original (see :mod:`kpmn_tracer.i18n`).

tests/test_i18n.py checks that every German text has an entry here with the same
placeholders.
"""

EN: dict[str, str] = {
    # ---------------------------------------------------------------- menus / actions
    "&Datei": "&File",
    "&Bearbeiten": "&Edit",
    "&Ansicht": "&View",
    "E&xtras": "E&xtras",
    "&Hilfe": "&Help",
    "Bearbeiten": "Edit",
    "Clip öffnen…": "Open clip…",
    "Clip öffnen": "Open clip",
    "Batch / Range-Session…": "Batch / range session…",
    "Projekt speichern": "Save project",
    "Exportieren…": "Export…",
    "Exportieren": "Export",
    "Frame als Bild speichern…": "Save frame as image…",
    "Frame als Bild speichern": "Save frame as image",
    "Projekt zurücksetzen…": "Reset project…",
    "Projekt zurücksetzen": "Reset project",
    "Einstellungen…": "Settings…",
    "Einstellungen": "Settings",
    "Beenden": "Quit",
    "Scorecard Studio öffnen": "Open Scorecard Studio",
    "Scorecard Studio": "Scorecard Studio",
    "Tastenkürzel": "Keyboard shortcuts",
    "Einführungstour": "Guided tour",
    "Rückgängig": "Undo",
    "Wiederholen": "Redo",
    "Neuer Schlag (Impact = Frame)": "New shot (impact = frame)",
    "Ballposition vom letzten Clip übernehmen": "Use ball position from the last clip",
    "Impact = aktueller Frame": "Impact = current frame",
    "Schlag bestätigen / aufheben": "Confirm / unconfirm shot",
    "Landung = aktueller Frame": "Landing = current frame",
    "Ausgewählten Punkt löschen": "Delete selected point",
    "Kamera tracken": "Track camera",
    "„Ball hier“-Punkte entfernen": "Remove “ball here” points",
    "Impacts erkennen": "Detect impacts",
    "Ball automatisch tracken": "Track ball automatically",
    "Werkzeug: {tool}": "Tool: {tool}",
    "Ansicht einpassen": "Fit view",
    "Frame vor": "Next frame",
    "Frame zurück": "Previous frame",
    "10 Frames vor": "10 frames forward",
    "10 Frames zurück": "10 frames back",
    "Abspielen / Pause": "Play / pause",
    "Zum Anfang": "Go to start",
    "Zum Ende": "Go to end",
    "Zum Impact": "Go to impact",
    "Nächster Schlag": "Next shot",
    "Vorheriger Schlag": "Previous shot",
    # ---------------------------------------------------------------- transport / preview
    "Anfang (Pos1)": "Start (Home)",
    "10 Frames zurück (Shift+←)": "10 frames back (Shift+←)",
    "Frame zurück (←)": "Previous frame (←)",
    "Abspielen/Pause (Leertaste)": "Play/pause (Space)",
    "Frame vor (→)": "Next frame (→)",
    "10 Frames vor (Shift+→)": "10 frames forward (Shift+→)",
    "Ende (Ende)": "End (End)",
    "Bild…": "Image…",
    "Aktuellen Frame mit Tracer als Bild speichern (Strg+Umschalt+E)":
        "Save the current frame with the tracer as an image (Ctrl+Shift+E)",
    "Clip öffnen (Strg+O) oder Datei hierher ziehen": "Open a clip (Ctrl+O) or drop a file here",
    "Zoom {z:.1f}×  (Doppelklick = einpassen)": "Zoom {z:.1f}×  (double-click = fit)",
    "Tracking-Konfidenz {conf:.0%}": "Tracking confidence {conf:.0%}",
    "Videos (*.mov *.mp4 *.m4v *.avi *.mkv);;Projekte (*.kpmntrace.json);;Alle Dateien (*)":
        "Videos (*.mov *.mp4 *.m4v *.avi *.mkv);;Projects (*.kpmntrace.json);;All files (*)",
    # ---------------------------------------------------------------- anchors / tools
    "Start": "Start",
    "Apex": "Apex",
    "Landung": "Landing",
    "Auswählen": "Select",
    "Zusatzpunkt": "Extra point",
    "Korrektur": "Correction",
    "Ball hier": "Ball here",
    "Punkte ziehen / auswählen": "Drag / select points",
    "Ball-Startpunkt im Impact-Frame setzen": "Set the ball's start point in the impact frame",
    "Höchsten Punkt der Flugbahn setzen": "Set the highest point of the flight",
    "Landepunkt setzen": "Set the landing point",
    "Zusätzlicher Kurvenpunkt (Draw/Fade)": "Additional curve point (draw/fade)",
    "Tracer in diesem Frame verschieben (Keyframe)": "Move the tracer in this frame (keyframe)",
    "Auf den Ball klicken: der Tracer-Kopf ist in diesem Frame genau dort":
        "Click the ball: the tracer head is exactly there in this frame",
    "Punkte mit der Maus ziehen. Entf löscht einen Zusatzpunkt.":
        "Drag points with the mouse. Del removes an extra point.",
    "Im Impact-Frame auf den Ball klicken.": "Click the ball in the impact frame.",
    "Auf den höchsten Punkt der Flugbahn klicken (beliebiger Frame).":
        "Click the highest point of the flight (any frame).",
    "Auf den Landepunkt klicken. Mit „Landung = Frame“ den Zeitpunkt setzen.":
        "Click the landing point. Set its time with “Landing = frame”.",
    "Klick fügt einen Kurvenpunkt hinzu (z. B. für Draw/Fade).": "A click adds a curve point (e.g. for a draw/fade).",
    "Klick = wo der Tracer-Kopf in diesem Frame sein soll (Korrektur-Keyframe).":
        "Click = where the tracer head should be in this frame (correction keyframe).",
    "Frame wählen, auf den Ball klicken: der Tracer-Kopf ist in diesem Frame genau dort. "
    "Zwei, drei Klicks direkt nach dem Impact reichen bei schnell wegfliegenden Bällen.":
        "Pick a frame, click the ball: the tracer head is exactly there in this frame. "
        "Two or three clicks right after impact are enough for fast balls.",
    # ---------------------------------------------------------------- main window messages
    "Abbrechen": "Cancel",
    "Analysiere {name} …\n(Proxy für die Vorschau wird erstellt)": "Analysing {name} …\n(creating the preview proxy)",
    "Fehler beim Öffnen": "Could not open the clip",
    "VFR → {n} Frames @ {fps:.3f} fps (1:1 wie in Resolve)": "VFR → {n} frames @ {fps:.3f} fps (1:1 as in Resolve)",
    "HDR ({fmt}) – Vorschau in SDR, Original unverändert": "HDR ({fmt}) – preview in SDR, original unchanged",
    "Gespeichertes Projekt geladen (1 Schlag). Neu anfangen: Datei › Projekt zurücksetzen":
        "Saved project loaded (1 shot). To start over: File › Reset project",
    "Gespeichertes Projekt geladen ({n} Schläge). Neu anfangen: Datei › Projekt zurücksetzen":
        "Saved project loaded ({n} shots). To start over: File › Reset project",
    "Impact Schlag {i}": "Impact shot {i}",
    "Landung Schlag {i}": "Landing shot {i}",
    "Korrektur-Keyframe": "Correction keyframe",
    "Impact-Kandidat {conf:.0%} ({src})": "Impact candidate {conf:.0%} ({src})",
    "Noch keine Ballposition gespeichert": "No ball position saved yet",
    "Ballposition übernommen – bitte im Impact-Frame prüfen":
        "Ball position applied – please check it in the impact frame",
    "Alle Schläge, die markierte Ballposition und die Impact-Kandidaten dieses Clips verwerfen?\n"
    "Stil und Text-Einstellungen bleiben erhalten. (Rückgängig mit Strg+Z)":
        "Discard all shots, the marked ball position and the impact candidates of this clip?\n"
        "Style and text settings are kept. (Undo with Ctrl+Z)",
    "Projekt zurückgesetzt": "Project reset",
    "Lande-Frame muss nach dem Impact liegen": "The landing frame must be after the impact",
    "„Ball hier“ geht nur zwischen Impact und Landung eines vollständigen Tracers":
        "“Ball here” only works between impact and landing of a complete tracer",
    "Personen-Maske + Kamera-Tracking …": "Person mask + camera tracking …",
    "Stativ erkannt": "Tripod detected",
    "Kamera getrackt": "Camera tracked",
    "Tracking fehlgeschlagen": "Tracking failed",
    "Personen-Maske wird berechnet …": "Computing the person mask …",
    "Personen-Maske": "Person mask",
    "Impacts werden gesucht …": "Searching for impacts …",
    "Audio + Video": "audio + video",
    "nur Audio (Ball nicht markiert)": "audio only (ball not marked)",
    "{n} Kandidaten, {sure} sicher – {src}. Magenta-Marker in der Timeline anklicken.":
        "{n} candidates, {sure} reliable – {src}. Click the magenta markers in the timeline.",
    "Impact-Erkennung": "Impact detection",
    "Kein offener Impact-Kandidat": "No open impact candidate",
    "Keine neuen sicheren Kandidaten": "No new reliable candidates",
    "{n} Schläge angelegt": "{n} shots created",
    "Erst einen Schlag anlegen (N) und den Ball markieren": "Create a shot first (N) and mark the ball",
    "Ball tracken": "Track ball",
    "Bitte im Impact-Frame zuerst mit „Start“ auf den Ball klicken.":
        "Please click the ball in the impact frame with “Start” first.",
    "Ball nicht gefunden – Punkte vorbefüllt, bitte von Hand setzen":
        "Ball not found – points pre-filled, please set them by hand",
    "Unsicher ({conf:.0%}) – Start/Apex/Landung vorbefüllt, bitte prüfen":
        "Uncertain ({conf:.0%}) – start/apex/landing pre-filled, please check",
    "Ball getrackt: {n} Detektionen, Konfidenz {conf:.0%}": "Ball tracked: {n} detections, confidence {conf:.0%}",
    "Ball wird getrackt …": "Tracking the ball …",
    "Clip analysieren": "Analyse clip",
    "Bitte zuerst in einem Frame mit ruhendem Ball einen Schlag anlegen (N) und mit „Start“ auf den Ball klicken.":
        "First create a shot (N) in a frame where the ball is at rest and click the ball with “Start”.",
    "{n} Schläge analysiert, {ok} sicher": "{n} shots analysed, {ok} reliable",
    "Clip wird analysiert …": "Analysing the clip …",
    "Speichern fehlgeschlagen": "Saving failed",
    "Gespeichert: {name}": "Saved: {name}",
    "Änderungen speichern?": "Save changes?",
    "Das Projekt wurde geändert. Speichern?": "The project has been changed. Save it?",
    "Export": "Export",
    "Noch kein vollständiger Tracer (Start + Landung) gesetzt.": "No complete tracer (start + landing) set yet.",
    "Bild wird gespeichert …": "Saving the image …",
    "Bild gespeichert: {path}": "Image saved: {path}",
    "Der Browser konnte nicht geöffnet werden.": "Could not open the browser.",
    "Exportiere {fmt} …": "Exporting {fmt} …",
    "Export fertig: {path}": "Export finished: {path}",
    "Export fehlgeschlagen": "Export failed",
    "Style speichern": "Save style",
    "Name des Presets:": "Preset name:",
    "Eingebaute Presets können nicht gelöscht werden": "Built-in presets cannot be deleted",
    "Schlag bestätigt": "Shot confirmed",
    "Bestätigung aufgehoben": "Confirmation removed",
    "Sprache / Language": "Language / Sprache",
    "Bitte warten, bis die laufende Berechnung fertig ist.": "Please wait until the running computation has finished.",
    # ---------------------------------------------------------------- side panels
    "wie Linie": "same as line",
    "Farbe wählen": "Choose colour",
    "Tracer-Style": "Tracer style",
    "Gespeicherte Styles": "Saved styles",
    "Speichern…": "Save…",
    "Aktuellen Style als Preset speichern": "Save the current style as a preset",
    "Löschen": "Delete",
    "Eigenes Preset löschen": "Delete your own preset",
    "Preset": "Preset",
    "Farbe": "Colour",
    "Glow-Farbe": "Glow colour",
    "Dicke": "Width",
    "Verjüngung": "Taper",
    "Deckkraft": "Opacity",
    "Weißer Kern": "White core",
    "Glow-Radius": "Glow radius",
    "Glow-Stärke": "Glow strength",
    "Schatten": "Shadow",
    "Schatten-Deckkraft": "Shadow opacity",
    "Voller Pfad bleibt stehen": "Full path stays",
    "Kurzer Schweif": "Short tail",
    "Modus": "Mode",
    "Schweif-Länge": "Tail length",
    "Ball-Punkt am Kopf": "Ball dot at the head",
    "Stehen nach Landung": "Hold after landing",
    "Ausblenden": "Fade out",
    "TV Rot": "TV red",
    "Gelb Schweif": "Yellow tail",
    "Weiß dezent": "Subtle white",
    "Blau mit Schatten": "Blue with shadow",
    "Text-Einblendung": "Text overlay",
    "z. B. 7-Eisen · 145 m  (leer = kein Text)": "e.g. 7 iron · 160 yd  (empty = no text)",
    "Am Apex": "At the apex",
    "Am Landepunkt": "At the landing point",
    "Oben links": "Top left",
    "Oben rechts": "Top right",
    "Unten links": "Bottom left",
    "Unten rechts": "Bottom right",
    "nach dem Impact": "after the impact",
    "nach der Landung": "after the landing",
    "Hintergrund-Box": "Background box",
    "Text (Schlag)": "Text (shot)",
    "Position": "Position",
    "Erscheint": "Appears",
    "Verzögerung": "Delay",
    "Schriftgröße": "Font size",
    "Schläge": "Shots",
    "Neuer Schlag": "New shot",
    "Neuen Schlag mit Impact = aktueller Frame anlegen (N)": "Create a new shot with impact = current frame (N)",
    "Ausgewählten Schlag löschen": "Delete the selected shot",
    "Impact = Frame": "Impact = frame",
    "Impact-Frame auf aktuellen Frame setzen (I)": "Set the impact frame to the current frame (I)",
    "Landung = Frame": "Landing = frame",
    "Lande-Frame auf aktuellen Frame setzen (O)": "Set the landing frame to the current frame (O)",
    "→ Impact": "→ Impact",
    "Zum Impact-Frame springen (Pos1)": "Jump to the impact frame (Home)",
    "Korrekturen löschen": "Clear corrections",
    "Alle Korrektur-Keyframes dieses Schlags entfernen": "Remove all correction keyframes of this shot",
    "Werkzeug": "Tool",
    "Automatik": "Automatic",
    "Impacts erkennen (D)": "Detect impacts (D)",
    "Schläge über Audio (Schlaggeräusch) und Video (Ball verlässt den Abschlagpunkt) finden":
        "Find shots by audio (the strike sound) and video (the ball leaves the tee)",
    "Kandidat übernehmen": "Adopt candidate",
    "Nächsten Kandidaten zum aktuellen Frame als Schlag anlegen":
        "Create a shot from the candidate nearest to the current frame",
    "Alle sicheren übernehmen": "Adopt all reliable",
    "Alle Kandidaten mit Konfidenz ≥ 50 % als Schläge anlegen":
        "Create shots from all candidates with confidence ≥ 50 %",
    "Ball tracken (B)": "Track ball (B)",
    "Flugbahn dieses Schlags automatisch verfolgen (Kamera, Maske, Ball)":
        "Follow this shot's flight automatically (camera, mask, ball)",
    "Ganzen Clip analysieren": "Analyse whole clip",
    "Alle Impacts finden und jeden Schlag automatisch tracken": "Find all impacts and track every shot automatically",
    "Vereinfachen": "Simplify",
    "Auto-Ergebnis auf Start/Apex/Landung reduzieren (bequemer von Hand nachzubessern)":
        "Reduce the automatic result to start/apex/landing (easier to adjust by hand)",
    "Tipp: zuerst den Ball mit „Start“ markieren – dann wird auch das Video ausgewertet.":
        "Tip: mark the ball with “Start” first – then the video is analysed as well.",
    "Kamera": "Camera",
    "Kamera tracken (T)": "Track camera (T)",
    "Kamerabewegung um diesen Schlag analysieren (Stativ wird automatisch erkannt)":
        "Analyse the camera motion around this shot (a tripod is detected automatically)",
    "Erzwingen": "Force",
    "Tracking auch dann durchführen, wenn ein Stativ erkannt würde": "Track even if a tripod would be detected",
    "nicht analysiert (Stativ angenommen)": "not analysed (tripod assumed)",
    "Flugkurve": "Flight curve",
    "Flugzeit Impact → Landung (bestimmt den Lande-Frame)": "Flight time impact → landing (sets the landing frame)",
    "Wie steil der Ball startet (0 = gerade Linie zum Apex)":
        "How steeply the ball launches (0 = straight line to the apex)",
    "Wie steil der Ball fällt": "How steeply the ball comes down",
    "Tempo direkt nach dem Impact (Easing)": "Speed right after impact (easing)",
    "Wie schnell der Ball nach dem Abflug abbremst": "How quickly the ball slows down after launch",
    "Beschleunigung auf dem Weg nach unten": "Acceleration on the way down",
    "Tracer hinter Golfer": "Tracer behind golfer",
    "Tracer dort ausschneiden, wo die Personen-Maske liegt": "Cut the tracer out where the person mask is",
    "Flugzeit": "Flight time",
    "Start-Steilheit": "Launch steepness",
    "Abstiegs-Steilheit": "Descent steepness",
    "Start-Tempo": "Launch speed",
    "Abbremsen": "Slow-down",
    "Spätes Tempo": "Late speed",
    "Schlag {i} – Frame {frame} ({t:.2f}s, {src}{conf})": "Shot {i} – frame {frame} ({t:.2f}s, {src}{conf})",
    "Handheld: Frames {a}–{b} getrackt, {bad} unsicher (rot in der Timeline)":
        "Handheld: frames {a}–{b} tracked, {bad} uncertain (red in the timeline)",
    "Stativ erkannt – keine Kompensation nötig": "Tripod detected – no compensation needed",
    " (inaktiv: Timing folgt den „Ball hier“-Punkten)": " (inactive: timing follows the “ball here” points)",
    # ---------------------------------------------------------------- dialogs
    "ProRes 4444 mit Alpha (.mov)": "ProRes 4444 with alpha (.mov)",
    "PNG-Sequenz mit Alpha": "PNG sequence with alpha",
    "Eingebrannt H.264 (.mp4)": "Burned-in H.264 (.mp4)",
    "Eingebrannt H.265 (.mp4)": "Burned-in H.265 (.mp4)",
    "Qualität für eingebrannte Exporte (kleiner = besser)": "Quality of burned-in exports (lower = better)",
    "Nur bestätigte Schläge": "Confirmed shots only",
    "Format": "Format",
    "Ziel": "Destination",
    "Zielordner": "Destination folder",
    "{w}×{h}, {n} Frames @ {fps:.3f} fps – identisch zum Clip.":
        "{w}×{h}, {n} frames @ {fps:.3f} fps – identical to the clip.",
    "Personen-Maske beim Tracking verwenden (MediaPipe)": "Use the person mask for tracking (MediaPipe)",
    "Selfie multiclass (Standard, inkl. Schläger)": "Selfie multiclass (default, includes the club)",
    "Pose (schnell, nur große Personen)": "Pose (fast, large persons only)",
    "DeepLab v3": "DeepLab v3",
    "Klassisch (Standard)": "Classic (default)",
    "YOLO (ML)": "YOLO (ML)",
    "Klassisch + YOLO": "Classic + YOLO",
    "Pfad zu best.pt (nur für YOLO; benötigt requirements-ml.txt)":
        "Path to best.pt (YOLO only; needs requirements-ml.txt)",
    "Frame für Frame (wie DaVinci Resolve)": "Frame by frame (like DaVinci Resolve)",
    "Zeitbasiert neu abtasten": "Resample by time",
    "Masken-Modell": "Mask model",
    "Ball-Erkennung": "Ball detection",
    "YOLO-Modell": "YOLO model",
    "VFR-Clips (neue Projekte)": "VFR clips (new projects)",
    "Standard-Exportformat": "Default export format",
    "Aktion": "Action",
    "Taste": "Key",
    "Maus: Rad = Zoom, rechte/mittlere Taste ziehen = verschieben, Doppelklick rechts = einpassen.":
        "Mouse: wheel = zoom, drag with the right/middle button = pan, right double-click = fit.",
    # ---------------------------------------------------------------- batch window
    "Batch – Range-Session": "Batch – range session",
    "Ordner mit Clips": "Folder with clips",
    "Ordner…": "Folder…",
    "Ordner:": "Folder:",
    "Analysieren": "Analyse",
    "Ballposition vom letzten Clip verwenden (gleicher Stativ-Standort)":
        "Use the ball position from the last clip (same tripod spot)",
    "Nur einschalten, wenn alle Clips vom selben Stativ-Platz aus gefilmt sind.":
        "Only switch this on if all clips were filmed from the same tripod spot.",
    "Bereits analysierte Clips neu berechnen": "Re-analyse clips that were already analysed",
    "Unbestätigte Schläge werden verworfen und neu gesucht, bestätigte bleiben.":
        "Unconfirmed shots are discarded and searched again, confirmed ones are kept.",
    "Bestätigen ab": "Confirm from",
    "Alle darüber bestätigen": "Confirm all above",
    "ProRes 4444 (Alpha)": "ProRes 4444 (alpha)",
    "PNG-Sequenz": "PNG sequence",
    "H.264 eingebrannt": "H.264 burned in",
    "H.265 eingebrannt": "H.265 burned in",
    "Bestätigte exportieren": "Export confirmed",
    "Häkchen = Schlag bestätigt. Doppelklick öffnet den Schlag im Editor zum Nachkorrigieren.":
        "Tick = shot confirmed. Double-click opens the shot in the editor for corrections.",
    "Ohne Ballposition werden Impacts nur über den Ton gefunden und nicht getrackt. "
    "Clips mit einem im Editor markierten Ball werden voll analysiert.":
        "Without a ball position, impacts are only found by sound and not tracked. "
        "Clips with a ball marked in the editor are fully analysed.",
    "Noch keine Ballposition gespeichert: einen Schlag im Editor setzen und speichern – die Ballposition wird gemerkt.":
        "No ball position saved yet: set a shot in the editor and save – the ball position is remembered.",
    "Ballposition vom letzten Clip: {x:.0%} / {y:.0%} des Bildes – wird pro Clip geprüft "
    "(nur verwendet, wenn dort ein Ball liegt).":
        "Ball position from the last clip: {x:.0%} / {y:.0%} of the frame – checked for every clip "
        "(only used if there is a ball).",
    "Bitte einen Ordner wählen.": "Please choose a folder.",
    "{name}\nFehler: {error}": "{name}\nError: {error}",
    "{name}\nkeine Schläge gefunden": "{name}\nno shots found",
    "{name} · Schlag {i}\n{t:.1f} s · Konfidenz {conf:.0%}": "{name} · shot {i}\n{t:.1f} s · confidence {conf:.0%}",
    "{n} Overlays exportiert:": "{n} overlays exported:",
    "Nichts bestätigt.": "Nothing confirmed.",
    # ---------------------------------------------------------------- errors from the analysis
    "Personen-Maske nicht verfügbar – eine Systembibliothek fehlt ({exc}). "
    "Ubuntu/Debian: sudo apt install libgles2 libegl1":
        "Person mask not available – a system library is missing ({exc}). "
        "Ubuntu/Debian: sudo apt install libgles2 libegl1",
    # ---------------------------------------------------------------- guided tour
    "Tour beenden": "End tour",
    "Zurück": "Back",
    "Weiter": "Next",
    "Los geht's": "Let's go",
    "Willkommen bei KPMN Tracer": "Welcome to KPMN Tracer",
    "Diese kurze Tour zeigt dir, was wo ist. Der Ablauf ist immer gleich:<br><br>"
    "<b>1.</b> Clip öffnen &nbsp;→&nbsp; <b>2.</b> Ball markieren &nbsp;→&nbsp; "
    "<b>3.</b> automatisch tracken lassen &nbsp;→&nbsp; <b>4.</b> prüfen und nachbessern "
    "&nbsp;→&nbsp; <b>5.</b> exportieren.<br><br>"
    "Mit <b>→</b> / <b>Enter</b> weiter, <b>Esc</b> beendet die Tour. Du findest sie jederzeit "
    "wieder unter <i>Hilfe › Einführungstour</i>.":
        "This short tour shows you what is where. The workflow is always the same:<br><br>"
        "<b>1.</b> open a clip &nbsp;→&nbsp; <b>2.</b> mark the ball &nbsp;→&nbsp; "
        "<b>3.</b> let it track automatically &nbsp;→&nbsp; <b>4.</b> check and adjust "
        "&nbsp;→&nbsp; <b>5.</b> export.<br><br>"
        "<b>→</b> / <b>Enter</b> continues, <b>Esc</b> ends the tour. You can start it again at any "
        "time under <i>Help › Guided tour</i>.",
    "Vorschau": "Preview",
    "Hier siehst du den Clip mit dem Tracer. Öffnen mit <b>Strg+O</b> oder die Videodatei einfach "
    "hierher ziehen.<br><br>"
    "Mausrad = zoomen, rechte Maustaste ziehen = verschieben, <b>F</b> = einpassen. "
    "Klicks ins Bild setzen Punkte – je nachdem, welches <i>Werkzeug</i> gerade aktiv ist.":
        "This is the clip with the tracer. Open one with <b>Ctrl+O</b> or simply drop the video file "
        "here.<br><br>"
        "Mouse wheel = zoom, drag with the right mouse button = pan, <b>F</b> = fit. "
        "Clicks into the picture set points – depending on which <i>tool</i> is active.",
    "Zeitleiste": "Timeline",
    "Klicken oder ziehen, um durch den Clip zu springen.<br><br>"
    "<span style='color:rgb(255,200,40)'>▲ gelb</span> = Impact eines Schlags, "
    "<span style='color:rgb(80,170,255)'>│ blau</span> = Landung, "
    "<span style='color:rgb(230,80,230)'>▲ magenta</span> = erkannter Impact-Kandidat, "
    "<span style='color:rgb(230,70,60)'>rot</span> = Frames, in denen das Kamera-Tracking "
    "unsicher ist.":
        "Click or drag to move through the clip.<br><br>"
        "<span style='color:rgb(255,200,40)'>▲ yellow</span> = impact of a shot, "
        "<span style='color:rgb(80,170,255)'>│ blue</span> = landing, "
        "<span style='color:rgb(230,80,230)'>▲ magenta</span> = detected impact candidate, "
        "<span style='color:rgb(230,70,60)'>red</span> = frames where the camera tracking "
        "is uncertain.",
    "Abspielen und Frame für Frame": "Playback and frame by frame",
    "<b>Leertaste</b> spielt ab, <b>← / →</b> gehen einen Frame, mit <b>Shift</b> zehn Frames. "
    "Rechts daneben steht, wo du bist – auch relativ zum Impact („Impact +12“).":
        "<b>Space</b> plays, <b>← / →</b> step one frame, with <b>Shift</b> ten frames. "
        "Next to it you see where you are – also relative to the impact (“Impact +12”).",
    "Ein Clip kann mehrere Schläge enthalten. Geh zu einem Frame, in dem der Ball noch ruhig "
    "liegt, und drück <b>N</b> (<i>Neuer Schlag</i>). Danach klickst du in der Vorschau auf den "
    "Ball – das ist der Startpunkt.":
        "A clip can contain several shots. Go to a frame where the ball is still at rest "
        "and press <b>N</b> (<i>New shot</i>). Then click the ball in the preview – "
        "that is the start point.",
    "Automatik – der schnelle Weg": "Automatic – the quick way",
    "Ist der Ball markiert, macht <b>Ball tracken (B)</b> den Rest: Kamerabewegung, Golfer und "
    "Ballflug werden analysiert, der Tracer entsteht von selbst.<br><br>"
    "<i>Ganzen Clip analysieren</i> findet alle Schläge eines langen Clips (über das Schlaggeräusch) "
    "und trackt jeden. Bei unsicherem Ergebnis sind Start, Apex und Landung vorbefüllt – "
    "du ziehst sie nur noch zurecht.":
        "Once the ball is marked, <b>Track ball (B)</b> does the rest: camera motion, golfer and "
        "ball flight are analysed and the tracer is created by itself.<br><br>"
        "<i>Analyse whole clip</i> finds all shots of a long clip (by the strike sound) "
        "and tracks each one. If a result is uncertain, start, apex and landing are pre-filled – "
        "you only drag them into place.",
    "Werkzeuge – von Hand setzen und korrigieren": "Tools – set and correct by hand",
    "<b>Start (S)</b>, <b>Apex (A)</b>, <b>Landung (L)</b>: die drei Punkte der Flugkurve. "
    "<b>Punkt (P)</b> biegt die Kurve (Draw/Fade).<br>"
    "<b>Ball hier (H)</b>: in einem Frame auf den Ball klicken – der Tracer-Kopf ist dann genau "
    "dort. Ideal, wenn der Tracer hinter dem Ball herhängt.<br>"
    "<b>Korrektur (K)</b>: verschiebt den Tracer nur in einzelnen Frames.<br>"
    "Mit <b>Auswählen (V)</b> ziehst du vorhandene Punkte.":
        "<b>Start (S)</b>, <b>Apex (A)</b>, <b>Landing (L)</b>: the three points of the flight curve. "
        "<b>Extra point (P)</b> bends the curve (draw/fade).<br>"
        "<b>Ball here (H)</b>: click the ball in a frame – the tracer head is then exactly "
        "there. Ideal when the tracer lags behind the ball.<br>"
        "<b>Correction (K)</b>: moves the tracer in single frames only.<br>"
        "With <b>Select (V)</b> you drag existing points.",
    "Kamera (aus der Hand gefilmt)": "Camera (filmed handheld)",
    "Wackelt die Kamera, rechnet <b>Kamera tracken (T)</b> die Bewegung heraus, damit der Tracer "
    "am Himmel „klebt“. Vom Stativ wird das automatisch erkannt. „Ball tracken“ erledigt das "
    "gleich mit.":
        "If the camera shakes, <b>Track camera (T)</b> removes the motion so the tracer “sticks” "
        "to the sky. A tripod is detected automatically. “Track ball” does this as well.",
    "Flugkurve feinjustieren": "Fine-tune the flight curve",
    "Flugzeit, wie steil der Ball startet und fällt und wie schnell er unterwegs ist. "
    "Nur für den manuellen Weg nötig.<br><br>"
    "<b>Tracer hinter Golfer</b> lässt den Tracer hinter dir verschwinden, wenn du vor der "
    "Flugbahn stehst.":
        "Flight time, how steeply the ball launches and comes down and how fast it travels. "
        "Only needed for the manual way.<br><br>"
        "<b>Tracer behind golfer</b> lets the tracer disappear behind you when you stand in front "
        "of the flight path.",
    "Aussehen": "Look",
    "Farbe, Dicke, Glow, Schatten, ganzer Pfad oder nur ein Schweif. Eigene Looks speicherst "
    "du als <b>Preset</b> und hast sie bei jedem Clip wieder.":
        "Colour, width, glow, shadow, the full path or just a tail. Save your own looks "
        "as a <b>preset</b> and have them for every clip.",
    "Optional ein Text zum Schlag, z. B. „7-Eisen · 145 m“ – animiert am Apex, am Landepunkt "
    "oder in einer Ecke.":
        "Optional text for the shot, e.g. “7 iron · 160 yd” – animated at the apex, at the landing "
        "point or in a corner.",
    "<b>Exportieren… (Strg+E)</b>: ProRes mit Transparenz für DaVinci Resolve (einfach über den "
    "Originalclip legen) oder ein fertiges MP4 zum direkten Posten.<br>"
    "<b>Bild… (Strg+Umschalt+E)</b>: der aktuelle Frame mit Tracer als Foto in voller Auflösung "
    "– für Bild-Beiträge.":
        "<b>Export… (Ctrl+E)</b>: ProRes with transparency for DaVinci Resolve (simply place it over "
        "the original clip) or a finished MP4 to post right away.<br>"
        "<b>Image… (Ctrl+Shift+E)</b>: the current frame with the tracer as a full-resolution photo "
        "– for picture posts.",
    "Menüs": "Menus",
    "<i>Datei</i>: Speichern (<b>Strg+S</b>), Batch für ganze Range-Sessions (<b>Strg+B</b>), "
    "<i>Projekt zurücksetzen</i> für einen Neuanfang.<br>"
    "<i>Extras</i>: das <b>Scorecard Studio</b> für Scorecard-Grafiken.<br>"
    "<i>Hilfe</i>: alle Tastenkürzel (<b>F1</b>) und diese Tour.<br><br>"
    "Viel Spaß – und schöne Schläge!":
        "<i>File</i>: save (<b>Ctrl+S</b>), batch for whole range sessions (<b>Ctrl+B</b>), "
        "<i>Reset project</i> to start over.<br>"
        "<i>Extras</i>: the <b>Scorecard Studio</b> for scorecard graphics.<br>"
        "<i>Help</i>: all keyboard shortcuts (<b>F1</b>) and this tour.<br><br>"
        "Have fun – and good shots!",
}
