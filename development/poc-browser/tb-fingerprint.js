/* poc-browser: Tor Browser fingerprint extractor.
 *
 * HOW TO RUN (on your real Tor Browser):
 *   1. Open Tor Browser at its DEFAULT window size — do NOT maximize or resize.
 *      Tor Browser letterboxes/rounds the viewport on purpose; the default
 *      rounded size is part of the fingerprint we must copy.
 *   2. Go to the onion you're targeting (or about:blank — it's all local probes).
 *   3. Open DevTools: Ctrl+Shift+K (Console).  If pasting is blocked, type
 *      `allow pasting` first, then paste this whole file and hit Enter.
 *   4. It prints a JSON blob AND copies it to your clipboard (Firefox `copy()`).
 *      Paste that back to me and I'll bake the exact values into the Playwright
 *      config so the automated client is indistinguishable from this browser.
 *
 * It makes NO network requests — nothing about your session leaves the browser.
 * Run it twice: canvas/audio hashes that CHANGE between runs mean RFP is
 * randomizing per-read (expected on Tor Browser) — that itself is a config fact.
 *
 * NOTE: JS cannot read its own HTTP request headers (UA string aside). For the
 * header ORDER + Accept/Accept-Language/Sec-* exactly as sent, also grab them
 * from DevTools > Network > (any request) > right-click > Copy Request Headers,
 * and paste those too.
 */
(() => {
  const safe = (fn, d = null) => { try { return fn(); } catch (e) { return `ERR:${e && e.name}`; } };

  const nav = navigator, scr = screen;
  const fp = {};

  fp.navigator = {
    userAgent: safe(() => nav.userAgent),
    appVersion: safe(() => nav.appVersion),
    platform: safe(() => nav.platform),
    oscpu: safe(() => nav.oscpu),
    vendor: safe(() => nav.vendor),
    vendorSub: safe(() => nav.vendorSub),
    productSub: safe(() => nav.productSub),
    language: safe(() => nav.language),
    languages: safe(() => (nav.languages || []).join(",")),
    hardwareConcurrency: safe(() => nav.hardwareConcurrency),
    deviceMemory: safe(() => nav.deviceMemory),
    maxTouchPoints: safe(() => nav.maxTouchPoints),
    doNotTrack: safe(() => nav.doNotTrack),
    globalPrivacyControl: safe(() => nav.globalPrivacyControl),
    webdriver: safe(() => nav.webdriver),
    cookieEnabled: safe(() => nav.cookieEnabled),
    pdfViewerEnabled: safe(() => nav.pdfViewerEnabled),
    userAgentData: safe(() => (nav.userAgentData ? JSON.stringify(nav.userAgentData) : "undefined")),
    plugins: safe(() => nav.plugins.length),
    mimeTypes: safe(() => nav.mimeTypes.length),
    buildID: safe(() => nav.buildID),
  };

  fp.screen = {
    width: safe(() => scr.width),
    height: safe(() => scr.height),
    availWidth: safe(() => scr.availWidth),
    availHeight: safe(() => scr.availHeight),
    colorDepth: safe(() => scr.colorDepth),
    pixelDepth: safe(() => scr.pixelDepth),
    orientation: safe(() => scr.orientation && scr.orientation.type),
  };

  fp.window = {
    innerWidth: safe(() => innerWidth),
    innerHeight: safe(() => innerHeight),
    outerWidth: safe(() => outerWidth),
    outerHeight: safe(() => outerHeight),
    devicePixelRatio: safe(() => devicePixelRatio),
    screenX: safe(() => screenX),
    screenY: safe(() => screenY),
  };

  fp.locale = {
    timeZone: safe(() => Intl.DateTimeFormat().resolvedOptions().timeZone),
    locale: safe(() => Intl.DateTimeFormat().resolvedOptions().locale),
    timezoneOffsetMin: safe(() => new Date().getTimezoneOffset()),
    dateSample: safe(() => new Date(0).toString()),
  };

  // WebGL — RFP masks vendor/renderer; capture what it reports.
  fp.webgl = safe(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
    if (!gl) return "no-webgl";
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      vendor: gl.getParameter(gl.VENDOR),
      renderer: gl.getParameter(gl.RENDERER),
      version: gl.getParameter(gl.VERSION),
      shadingLanguage: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
      unmaskedVendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : "blocked",
      unmaskedRenderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "blocked",
      maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
    };
  });

  // Canvas text hash — run the script twice; a CHANGING hash == RFP per-read noise.
  fp.canvasHash = safe(() => {
    const c = document.createElement("canvas");
    c.width = 240; c.height = 60;
    const ctx = c.getContext("2d");
    ctx.textBaseline = "top";
    ctx.font = "14px 'Arial'";
    ctx.fillStyle = "#f60"; ctx.fillRect(0, 0, 240, 60);
    ctx.fillStyle = "#069"; ctx.fillText("poc-browser \u{1F311} fp", 2, 15);
    ctx.strokeStyle = "rgba(0,0,0,0.5)"; ctx.beginPath();
    ctx.arc(120, 30, 20, 0, Math.PI * 2); ctx.stroke();
    const data = c.toDataURL();
    let h = 0; for (let i = 0; i < data.length; i++) { h = (h * 31 + data.charCodeAt(i)) >>> 0; }
    return h.toString(16);
  });

  // AudioContext fingerprint surface.
  fp.audio = safe(() => {
    const AC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!AC) return "no-audiocontext";
    const ac = new AC(1, 44100, 44100);
    return { sampleRate: ac.sampleRate, state: ac.state, maxChannels: ac.destination.maxChannelCount };
  });

  // Font-probing surface — RFP bundles a fixed font set; measure a handful.
  fp.fonts = safe(() => {
    const probe = ["Arial", "Times New Roman", "Courier New", "Comic Sans MS", "Ubuntu", "DejaVu Sans"];
    const span = document.createElement("span");
    span.style.cssText = "position:absolute;left:-9999px;font-size:72px";
    span.textContent = "mmmmmmmmmmlli";
    document.body.appendChild(span);
    const widths = {};
    for (const f of probe) { span.style.fontFamily = `'${f}',monospace`; widths[f] = span.offsetWidth; }
    document.body.removeChild(span);
    return widths;
  });

  fp.misc = {
    touchSupport: safe(() => "ontouchstart" in window),
    webrtc: safe(() => (window.RTCPeerConnection ? "present" : "absent")),
    battery: safe(() => (nav.getBattery ? "api-present" : "absent")),
    connection: safe(() => (nav.connection ? JSON.stringify({ et: nav.connection.effectiveType }) : "absent")),
    performanceTiming: safe(() => (window.performance && performance.now ? "present" : "absent")),
    href: safe(() => location.href),
    capturedAt: new Date().toISOString(),
  };

  const out = JSON.stringify(fp, null, 2);
  console.log("%c=== Tor Browser fingerprint (copy this) ===", "color:#743093;font-weight:bold");
  console.log(out);
  try { copy(out); console.log("%c[copied to clipboard]", "color:#0a0"); }
  catch (e) { console.log("(clipboard copy unavailable — select the JSON above and copy manually)"); }
  return fp;
})();
