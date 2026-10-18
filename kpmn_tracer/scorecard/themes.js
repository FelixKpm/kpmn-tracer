/* Built-in designs of the KPMN Scorecard Studio.

   A design only describes colours, fonts, background, logo and the two brand texts;
   the layout is the same for all of them. Own designs are made in the Studio
   ("Design" panel) and can be exported/imported as JSON files of the same shape.

   colors: bgTop/bgBottom (background gradient), header (table header row),
           accent (highlights, birdies, totals), text, muted.
           Optional, otherwise derived: headerText, accentInk (text on accent), muted2, slate.
   background: "fairway" (night-range fairway + tracer arc), "stripes" (mown stripes), "plain".
   fonts: a key of SCORECARD_FONTS in studio.html.
   logo: data URL (PNG/JPEG) or null; logoShape: "circle" | "square".
*/
window.SCORECARD_THEMES = [
  {
    id: "nightrange", name: "NightRange · teeoff.kpmn",
    colors: { bgTop: "#0C1A31", bgBottom: "#13233F", header: "#1B3A66", headerText: "#FFFFFF",
              accent: "#C6F432", accentInk: "#0B1528", text: "#FFFFFF", muted: "#9FB0CC",
              muted2: "#6F82A3", slate: "#5E7194" },
    fonts: "barlow", background: "fairway", logoShape: "circle",
    brand: "teeoff.kpmn", handle: "@teeoff.kpmn",
    logo: null
  },
  {
    id: "clubhaus", name: "Clubhaus (hell)",
    colors: { bgTop: "#F8F4EA", bgBottom: "#EEE6D4", header: "#23503C", accent: "#B8892E",
              text: "#1C2B24", muted: "#5D6B62" },
    fonts: "oswald", background: "plain", logoShape: "circle", brand: "", handle: "", logo: null
  },
  {
    id: "fairway", name: "Fairway (grün)",
    colors: { bgTop: "#0E2A1C", bgBottom: "#173F2A", header: "#21573A", accent: "#F2C94C",
              text: "#FFFFFF", muted: "#A8C3B2" },
    fonts: "barlow", background: "stripes", logoShape: "circle", brand: "", handle: "", logo: null
  },
  {
    id: "minimal", name: "Minimal (weiß)",
    colors: { bgTop: "#FFFFFF", bgBottom: "#F1F3F6", header: "#111827", accent: "#E63946",
              text: "#111827", muted: "#6B7280" },
    fonts: "inter", background: "plain", logoShape: "square", brand: "", handle: "", logo: null
  },
  {
    id: "mono", name: "Mono (schwarz)",
    colors: { bgTop: "#0A0A0A", bgBottom: "#1C1C1C", header: "#2A2A2A", accent: "#FFFFFF",
              text: "#FFFFFF", muted: "#A3A3A3" },
    fonts: "archivo", background: "plain", logoShape: "circle", brand: "", handle: "", logo: null
  }
];
