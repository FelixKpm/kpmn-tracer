# KPMN Tracer

Windows-Desktop-App, die Golf-Videos (Driving Range, iPhone) mit einem TV-ähnlichen Ball-Tracer
versieht. Das Overlay wird mit Alpha-Kanal exportiert und in DaVinci Resolve über den Clip gelegt.

> Status und Details: siehe [PROGRESS.md](PROGRESS.md) und [DECISIONS.md](DECISIONS.md).

## Installation (Entwicklung)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python tools\fetch_ffmpeg.py   # lädt ffmpeg + ffprobe nach vendor\ffmpeg
.venv\Scripts\python -m kpmn_tracer           # startet die GUI
```

Tests: `.venv\Scripts\python -m pytest`

## Kurzbedienung (manueller Modus)

1. Clip öffnen (Strg+O oder per Drag & Drop). Beim ersten Öffnen wird ein Vorschau-Proxy erstellt.
2. Zum Schlagmoment scrubben, **N** = neuer Schlag (Impact = aktueller Frame).
3. Auf den Ball klicken (Start), dann auf den höchsten Punkt (Apex), dann auf den Landepunkt.
4. Zum Landezeitpunkt gehen und **O** drücken (oder die Flugzeit im Panel einstellen).
5. Style rechts anpassen, **Strg+E** exportieren.

| Taste | Aktion |
|---|---|
| ← / → | Frame zurück / vor (mit Shift: 10 Frames) |
| Leertaste | Abspielen / Pause |
| N / I / O | Neuer Schlag / Impact = Frame / Landung = Frame |
| V S A L P K | Werkzeuge Auswählen, Start, Apex, Landung, Zusatzpunkt, Korrektur |
| Entf | Ausgewählten Zusatzpunkt löschen |
| Strg+Z / Strg+Y | Rückgängig / Wiederholen |
| Mausrad / rechte Maustaste ziehen | Zoom / Verschieben, Doppelklick rechts bzw. F = einpassen |

## Kommandozeile

```powershell
python -m kpmn_tracer probe clip.mov
python -m kpmn_tracer export clip.mov --format prores   # nutzt clip.mov.kpmntrace.json
```
