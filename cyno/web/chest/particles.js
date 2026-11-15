/* Cynobot particle stage: one WebGL point cloud that flows between shapes.

   No libraries, so it works with no internet. All motion runs in the vertex shader on the
   graphics chip; JavaScript only uploads a new target shape when the state changes.
   States: idle (a breathing globe, aurora bands or a constellation, see IDLE_STYLES), topic (a line drawing for what Cynobot is talking about), listen (a ring that ripples with the voice),
   think (a slow swirl), answer (a flowing wave), games (a calm horizon).

     const stage = CynoParticles.create(canvas);
     stage.setState('listen'); stage.setLevel(0.6); stage.setTheme('BLUE'); stage.burst();

   Built for a laptop with integrated graphics: it watches its own frame rate and draws
   fewer particles if it falls behind, and it stops drawing while the page is hidden. */
(function () {
  const VERT = `
    attribute vec4 aFrom;   // xyz + group (0 shape, 9 dust)
    attribute vec4 aTo;
    attribute vec4 aSeed;
    uniform float uMix, uTime, uLevel, uFlow, uRipple, uSpin, uSpinAngle, uWave, uBurst, uSize, uScale, uAspect;
    uniform vec2 uOffset, uTilt, uFrame;  // uFrame: where the shape sits on screen (y), and its zoom
    uniform vec3 uColA, uColB, uColC;
    varying vec4 vColor;

    // w: how much each idle part's own motion applies (x globe, y orbit ring, z aurora, w stars).
    // It eases in and out with each particle's morph, so changing shape never jumps.
    vec3 behave(vec3 p, vec4 w, float t) {
      // A slow swell travels along aurora bands and topic drawings.
      float swell = uFlow * (1.0 - w.x - w.y - w.w);
      p.y += swell * sin(p.x * 3.0 - t * 0.9) * 0.05;
      p.z += swell * cos(p.x * 2.4 - t * 0.7) * 0.10;
      // Breathing globe: it turns slowly and swells a little, like breathing.
      float ga = t * 0.32 * w.x;
      p = vec3(p.x * cos(ga) + p.z * sin(ga), p.y, -p.x * sin(ga) + p.z * cos(ga));
      p *= 1.0 + 0.05 * sin(t * 1.15) * w.x;
      // Its dotted ring orbits on a tilt.
      float ra = t * 0.55 * w.y;
      p = vec3(p.x * cos(ra) + p.z * sin(ra), p.y, -p.x * sin(ra) + p.z * cos(ra));
      float tx = 0.42 * w.y, tz = 0.3 * w.y;
      p = vec3(p.x, p.y * cos(tx) - p.z * sin(tx), p.y * sin(tx) + p.z * cos(tx));
      p = vec3(p.x * cos(tz) - p.y * sin(tz), p.x * sin(tz) + p.y * cos(tz), p.z);
      // Aurora: the bands roll sideways.
      p.y += w.z * sin(p.x * 2.2 + t * 0.8 + p.z * 4.0) * 0.07;
      // Constellation: drifts a touch.
      p.xy *= 1.0 + 0.015 * sin(t * 0.9) * w.w;
      float r = length(p.xy) + 0.0001;
      float ang = atan(p.y, p.x);
      // Listening ring: ripples grow with the voice level.
      vec2 dir = p.xy / r;
      float rip = sin(ang * 6.0 + t * 2.4) * 0.030 + sin(ang * 11.0 - t * 3.1) * 0.018 + sin(ang * 3.0 + t * 1.3) * 0.022;
      p.xy += dir * uRipple * rip * (0.45 + uLevel * 3.2);
      // Thinking: inner particles turn faster, like a small galaxy.
      // The angle is how far it has turned since thinking began; it unwinds when thinking ends.
      float a = uSpin * uSpinAngle * (0.25 + 0.55 / (0.35 + r));
      float ca = cos(a), sa = sin(a);
      p.xy = vec2(p.x * ca - p.y * sa, p.x * sa + p.y * ca);
      // Answering: rolling wave, taller when Cynobot speaks louder.
      p.y += uWave * (sin(p.x * 3.2 + t * 1.5 + p.z * 5.0) * 0.085 + sin(p.x * 7.0 - t * 2.2 + p.z * 3.0) * 0.035) * (0.55 + uLevel * 2.2);
      return p;
    }

    void main() {
      float t = uTime;
      // Each particle leaves at its own moment, so the shape flows instead of snapping.
      float m = smoothstep(aSeed.x * 0.45, aSeed.x * 0.45 + 0.55, uMix);
      float group = mix(aFrom.w, aTo.w, step(0.5, m));
      vec3 p = mix(aFrom.xyz, aTo.xyz, m);
      // A gentle arc on the way, so particles curve through space.
      p += vec3(aSeed.y - 0.5, aSeed.z - 0.5, aSeed.w - 0.5) * sin(m * 3.14159) * 0.55;
      // Which idle part this particle belongs to, eased across the morph.
      vec4 w = vec4(0.0);
      for (int k = 1; k <= 4; k++) {
        float fk = float(k);
        float on = (1.0 - step(0.5, abs(aFrom.w - fk))) * (1.0 - m) + (1.0 - step(0.5, abs(aTo.w - fk))) * m;
        if (k == 1) w.x = on; else if (k == 2) w.y = on; else if (k == 3) w.z = on; else w.w = on;
      }
      if (group < 8.5) p = behave(p, w, t);
      // Idle drift, and the outward kick of a celebration.
      p += vec3(sin(t * 0.9 + aSeed.x * 40.0), cos(t * 0.8 + aSeed.y * 40.0), sin(t * 0.7 + aSeed.z * 40.0)) * 0.012;
      p += normalize(p + vec3(0.0001)) * uBurst * (0.35 + aSeed.w * 1.1);

      if (group < 8.5) p.xy = p.xy * uFrame.y + uOffset;
      // Slow camera sway plus the visitor's finger.
      float ry = uTilt.x + sin(t * 0.23) * 0.04, rx = uTilt.y + sin(t * 0.17) * 0.025;
      float cy = cos(ry), sy = sin(ry), cx = cos(rx), sx = sin(rx);
      p = vec3(p.x * cy + p.z * sy, p.y, -p.x * sy + p.z * cy);
      p = vec3(p.x, p.y * cx - p.z * sx, p.y * sx + p.z * cx);

      float depth = 3.2 - p.z;
      vec2 s = p.xy * (2.6 / depth) * uScale;
      if (group < 8.5) s.y += uFrame.x;
      gl_Position = vec4(s.x / uAspect, s.y, 0.0, 1.0);
      float near = 3.2 / depth;
      float zoom = group < 8.5 ? mix(0.55, 1.0, clamp(uFrame.y, 0.0, 1.0)) : 1.0;  // smaller shape, finer points
      gl_PointSize = uSize * zoom * near * (0.55 + aSeed.y * 0.9) * (group > 8.5 ? 0.8 : 1.0);

      // Colour sweeps across the scene; dust is dim.
      float g = clamp(s.x / uAspect * 0.5 + 0.5 + (aSeed.z - 0.5) * 0.25, 0.0, 1.0);
      vec3 col = g < 0.5 ? mix(uColA, uColB, g * 2.0) : mix(uColB, uColC, g * 2.0 - 1.0);
      float alpha = (0.30 + aSeed.w * 0.55) * clamp(near, 0.75, 1.4);
      if (group > 8.5) alpha *= 0.5;
      alpha *= mix(1.0, 0.45 + 0.55 * (0.5 + 0.5 * sin(t * 2.6 + aSeed.x * 30.0)), w.w);  // stars twinkle
      vColor = vec4(col, alpha);
    }`;
  const FRAG = `
    precision mediump float;
    varying vec4 vColor;
    void main() {
      float d = length(gl_PointCoord - 0.5);
      float a = smoothstep(0.5, 0.05, d);
      gl_FragColor = vec4(vColor.rgb * vColor.a * a, vColor.a * a);
    }`;

  // Colours normally come from /shared/theme.css (--cy-p1..3), the file the face screen uses too.
  // These are only for a page without it (stage-test.html).
  const THEMES = {
    RED: [[1.0, 0.16, 0.24], [0.72, 0.03, 0.10], [1.0, 0.74, 0.76]],
    BLUE: [[0.0, 0.9, 1.0], [0.0, 0.42, 0.85], [0.78, 0.97, 1.0]],
  };
  // Read the theme's particle colours from the page's CSS; null if the page has none.
  function cssColors() {
    const st = getComputedStyle(document.body);
    const out = ['--cy-p1', '--cy-p2', '--cy-p3'].map((n) => st.getPropertyValue(n).split(',').map((v) => parseFloat(v) / 255));
    return out.every((c) => c.length === 3 && c.every((v) => v >= 0 && v <= 1)) ? out : null;
  }
  // Behaviour per state: ripple, spin, wave strength, and where the shape sits (x, y).
  const STATES = {
    // framed: the shape is centred in the free area the page reports with setFrame().
    idle: { ripple: 0, flow: 1, spin: 0, wave: 0, offset: [0, 0], framed: true },
    listen: { ripple: 1, spin: 0, wave: 0, offset: [0, 0], framed: true },
    think: { ripple: 0.2, spin: 1, wave: 0, offset: [0, 0], framed: true },
    answer: { ripple: 0, spin: 0, wave: 1, offset: [0, -0.62] },
    games: { ripple: 0, spin: 0, wave: 0.25, offset: [0, -0.86] },
    topic: { ripple: 0, flow: 0.25, spin: 0, wave: 0, offset: [0, 0], framed: true },
  };
  const QUALITY = [5000, 9000, 15000, 24000];

  // Topic shapes: simple line drawings (24 x 24 grid, same style as the screen's icons) that
  // the particles trace when Cynobot talks about that topic.
  const ICONS = {
    pin: 'M12 21s-6.5-5.6-6.5-10.5a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21z M9.7 10.5a2.3 2.3 0 1 0 4.6 0a2.3 2.3 0 1 0-4.6 0',
    cap: 'M2.5 9.5 12 5l9.5 4.5L12 14 2.5 9.5z M6.5 11.7V16c1.6 1.3 3.4 2 5.5 2s3.9-.7 5.5-2v-4.3 M21.5 9.5v5',
    mail: 'M5.5 5.5h13a2.5 2.5 0 0 1 2.5 2.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16V8a2.5 2.5 0 0 1 2.5-2.5z M4 7.5l8 6 8-6',
    phone: 'M6.5 3.5h3l1.5 4-2 1.5a11 11 0 0 0 6 6l1.5-2 4 1.5v3a2 2 0 0 1-2 2A16 16 0 0 1 4.5 5.5a2 2 0 0 1 2-2z',
    book: 'M12 6.5C10.2 5.2 7.5 4.8 4 5v13c3.5-.2 6.2.2 8 1.5 1.8-1.3 4.5-1.7 8-1.5V5c-3.5-.2-6.2.2-8 1.5z M12 6.5v13',
    globe: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0 M3 12h18 M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9s1.3-6.5 3.8-9z',
    people: 'M5.5 8a3 3 0 1 0 6 0a3 3 0 1 0-6 0 M3 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5 M15.5 5.6a2.6 2.6 0 0 1 0 5 M17 14.2c2.3.5 4 2.3 4 4.8',
    chip: 'M7 7h10v10H7z M10 10h4v4h-4z M9.5 3v4 M14.5 3v4 M9.5 17v4 M14.5 17v4 M3 9.5h4 M3 14.5h4 M17 9.5h4 M17 14.5h4',
    building: 'M5 21V5.5L12 3l7 2.5V21 M3 21h18 M9.5 21v-4h5v4 M9 8.5h.01 M12 8.5h.01 M15 8.5h.01 M9 12.5h.01 M12 12.5h.01 M15 12.5h.01',
  };
  const iconCache = {};
  /** Points along an icon's lines, as [x, y] pairs in shape units (about -0.75..0.75). */
  function iconPoints(name) {
    if (iconCache[name]) return iconCache[name];
    const size = 200, c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.scale(size / 24, size / 24);
    ctx.lineWidth = 0.9; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#fff';
    ctx.stroke(new Path2D(ICONS[name]));
    const data = ctx.getImageData(0, 0, size, size).data, pts = [];
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (data[(y * size + x) * 4 + 3] > 110) pts.push((x / size - 0.5) * 1.5, (0.5 - y / size) * 1.5);
    return (iconCache[name] = pts.length ? pts : [0, 0]);
  }

  // ---- idle shapes ----
  const IDLE_STYLES = ['globe', 'aurora', 'stars'];
  let idleStyle = 'globe';
  // Constellation C: stars on an open "C" (for Cynobot and Cynocor), joined by faint lines.
  const STAR_NODES = (() => {
    const out = [];
    for (let k = 0; k < 13; k++) {
      const a = 0.75 + (k / 12) * (2 * Math.PI - 1.5), r = 0.62 + Math.sin(k * 2.7) * 0.06;
      out.push([Math.cos(a) * r, Math.sin(a) * r * 0.92, Math.sin(k * 1.9) * 0.12]);
    }
    return out;
  })();
  const STAR_LINKS = [...STAR_NODES.slice(1).map((_, k) => [k, k + 1]), [1, 4], [5, 8], [8, 11], [2, 6]];
  /** One idle particle: [x, y, z, group] (1 globe, 2 orbit ring, 3 aurora, 4 star). */
  function idlePoint(i, u) {
    const frac = (v) => v - Math.floor(v);
    if (idleStyle === 'aurora') {  // three soft bands of light flowing sideways
      const band = i % 3, x = (u * 2 - 1) * 1.55;
      return [x, (band - 1) * 0.24 + Math.sin(x * 1.8 + band * 1.3) * 0.17 + gauss() * 0.03 * (1 + band * 0.4),
        (band - 1) * 0.28 + gauss() * 0.05, 3];
    }
    if (idleStyle === 'stars') {
      if (frac(i * 0.381966) < 0.38) {  // the stars themselves
        const n = STAR_NODES[i % STAR_NODES.length];
        return [n[0] + gauss() * 0.014, n[1] + gauss() * 0.014, n[2] + gauss() * 0.02, 4];
      }
      const [a, b] = STAR_LINKS[i % STAR_LINKS.length], f = rnd(), A = STAR_NODES[a], B = STAR_NODES[b];
      return [A[0] + (B[0] - A[0]) * f + gauss() * 0.005, A[1] + (B[1] - A[1]) * f + gauss() * 0.005, A[2] + (B[2] - A[2]) * f, 4];
    }
    // Breathing globe: points spread evenly over a sphere, and a dotted ring around it.
    if (frac(i * 0.2763932) < 0.72) {
      const zz = rnd() * 2 - 1, r = Math.sqrt(1 - zz * zz), a = rnd() * Math.PI * 2;  // random, so no stripes show
      const R = 0.46 + gauss() * 0.014;
      return [Math.cos(a) * r * R, zz * R, Math.sin(a) * r * R, 1];
    }
    const a = Math.floor(rnd() * 28) / 28 * Math.PI * 2 + rnd() * 0.12;  // 28 dashes, so its turning shows
    const R = 0.8 + gauss() * 0.012;
    return [Math.cos(a) * R, gauss() * 0.01, Math.sin(a) * R, 2];
  }

  const rnd = Math.random;
  const gauss = () => (rnd() + rnd() + rnd() + rnd() - 2) / 2;

  /** Target positions for a state: Float32Array of x, y, z, group per particle. */
  function shape(name, n, icon) {
    const pts = name === 'topic' ? iconPoints(icon) : null;
    const out = new Float32Array(n * 4);
    const frac = (v) => v - Math.floor(v);
    for (let i = 0; i < n; i++) {
      let x = 0, y = 0, z = 0, g = 0;
      // Parts are spread evenly through the list, so drawing fewer particles (lower
      // quality) thins every part instead of dropping whole ones.
      const u = frac(i * 0.6180339887), dust = frac(i * 0.7548776662) > 0.9;
      if (dust) {  // loose dust that gives the scene depth
        x = (rnd() - 0.5) * 5.2; y = (rnd() - 0.5) * 3.2; z = (rnd() - 0.5) * 3.0 - 0.4; g = 9;
      } else if (name === 'idle') {
        // Not a face (the head display is the face), and not a figure of eight (another brand uses it).
        [x, y, z, g] = idlePoint(i, u);
      } else if (name === 'topic') {
        const k = Math.floor(rnd() * (pts.length / 2)) * 2;
        x = pts[k] + gauss() * 0.012; y = pts[k + 1] + gauss() * 0.012; z = gauss() * 0.05;
      } else if (name === 'listen') {
        const a = rnd() * Math.PI * 2, r = 0.62 + gauss() * 0.045;
        x = Math.cos(a) * r; y = Math.sin(a) * r; z = gauss() * 0.12;
      } else if (name === 'think') {
        const arm = i % 3, r = 0.05 + Math.pow(rnd(), 0.75) * 0.66, a = arm * 2.094 + r * 4.2 + gauss() * 0.42;
        x = Math.cos(a) * r; y = Math.sin(a) * r; z = gauss() * 0.08 * (1 - r);
      } else {  // answer and games: a field of points receding into the distance
        const u = rnd(), d = rnd();
        x = (u * 2 - 1) * (1.9 + d * 1.4); z = 0.5 - d * 2.6; y = gauss() * 0.012 + d * 0.16;
      }
      out[i * 4] = x; out[i * 4 + 1] = y; out[i * 4 + 2] = z; out[i * 4 + 3] = g;
    }
    return out;
  }

  function create(canvas, opts = {}) {
    const gl = canvas.getContext('webgl', { alpha: true, antialias: false, premultipliedAlpha: true, powerPreference: 'high-performance' });
    if (!gl) return null;  // caller keeps the plain background

    const compile = (type, src) => {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    const U = {};
    ['uMix', 'uTime', 'uLevel', 'uFlow', 'uRipple', 'uSpin', 'uSpinAngle', 'uWave', 'uBurst', 'uSize', 'uScale', 'uAspect', 'uOffset', 'uTilt', 'uFrame', 'uColA', 'uColB', 'uColC']
      .forEach((n) => (U[n] = gl.getUniformLocation(prog, n)));

    const MAX = QUALITY[QUALITY.length - 1];
    let quality = Math.min(QUALITY.length - 1, opts.quality ?? 2);
    let count = QUALITY[quality];
    const seeds = new Float32Array(MAX * 4).map(() => rnd());
    const buffer = (name, data, usage) => {
      const b = gl.createBuffer(), loc = gl.getAttribLocation(prog, name);
      gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, usage);
      gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0);
      return b;
    };
    buffer('aSeed', seeds, gl.STATIC_DRAW);
    let state = opts.state || 'idle';
    let fromData = shape(state, MAX), toData = fromData.slice();
    const fromBuf = buffer('aFrom', fromData, gl.DYNAMIC_DRAW);
    const toBuf = buffer('aTo', toData, gl.DYNAMIC_DRAW);
    const upload = (buf, data) => { gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferSubData(gl.ARRAY_BUFFER, 0, data); };

    // Which graphics chip is drawing (a name with "SwiftShader" or "llvmpipe" means no chip: slow).
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = String(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)).slice(0, 120);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);  // additive: overlapping points glow
    gl.clearColor(0, 0, 0, 0);

    // Animated values ease toward their targets every frame.
    const cur = { ripple: STATES[state].ripple, spin: STATES[state].spin, wave: STATES[state].wave, ox: STATES[state].offset[0], oy: STATES[state].offset[1], level: 0, tiltX: 0, tiltY: 0, burst: 0, flow: STATES[state].flow || 0 };
    let spinAngle = 0;
    let frameY = 0.12, frameZoom = 1;  // defaults suit a page that never calls setFrame()
    cur.fy = STATES[state].framed ? frameY : 0; cur.fz = STATES[state].framed ? frameZoom : 1;
    let mix = 1, mixStart = 0, level = 0, tiltX = 0, tiltY = 0, themeName = opts.theme || 'RED';
    const pickColors = () => cssColors() || THEMES[themeName] || THEMES.RED;
    let colors = pickColors();
    // The page switches Red/Blue by a class on <body>; follow it (and fade to the new colours).
    // Right after the page opens, jump straight to the theme (no red-to-blue fade on start).
    const applyColors = () => { colors = pickColors(); if (clock < 2) curColors = colors.map((c) => c.slice()); };
    new MutationObserver(applyColors).observe(document.body, { attributes: true, attributeFilter: ['class'] });
    let curColors = colors.map((c) => c.slice());
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const MORPH_MS = reduced ? 1 : 1500;
    let running = true, raf = 0, last = performance.now(), clock = 0;
    let frames = 0, slowSince = 0, fps = 60, fpsAt = last, autoQuality = opts.autoQuality !== false;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);  // sharper than this costs speed for no visible gain
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
      const aspect = w / h;
      gl.uniform1f(U.uAspect, aspect);
      gl.uniform1f(U.uScale, Math.min(1, aspect / 1.25));  // keep the shape inside narrow screens
      gl.uniform1f(U.uSize, Math.max(2.2, h / 300) * (quality === 0 ? 1.35 : 1));
    }

    function frame(now) {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - last) / 1000); last = now; clock += dt;
      resize();
      const k = 1 - Math.pow(0.001, dt);  // frame-rate independent easing
      const target = STATES[state];
      cur.ripple += (target.ripple - cur.ripple) * k * 0.6;
      cur.spin += (target.spin - cur.spin) * k * 0.6;
      if (target.spin > 0) spinAngle = Math.min(12, spinAngle + dt); else if (cur.spin < 0.01) spinAngle = 0;
      cur.wave += (target.wave - cur.wave) * k * 0.6;
      cur.ox += (target.offset[0] - cur.ox) * k * 0.5;
      cur.oy += (target.offset[1] - cur.oy) * k * 0.5;
      cur.fy += ((target.framed ? frameY : 0) - cur.fy) * k * 0.5;
      cur.fz += ((target.framed ? frameZoom : 1) - cur.fz) * k * 0.5;
      cur.level += (level - cur.level) * Math.min(1, dt * 14);
      cur.tiltX += (tiltX - cur.tiltX) * k * 0.5;
      cur.tiltY += (tiltY - cur.tiltY) * k * 0.5;
      cur.burst *= Math.pow(0.02, dt);
      curColors.forEach((c, i) => c.forEach((v, j) => (c[j] = v + (colors[i][j] - v) * k * 0.4)));
      mix = Math.min(1, (now - mixStart) / MORPH_MS);
      cur.flow += ((target.flow || 0) - cur.flow) * k * 0.6;

      gl.uniform1f(U.uMix, mix); gl.uniform1f(U.uTime, reduced ? 0 : clock); gl.uniform1f(U.uLevel, cur.level);
      gl.uniform1f(U.uFlow, cur.flow); gl.uniform1f(U.uRipple, cur.ripple); gl.uniform1f(U.uSpin, cur.spin); gl.uniform1f(U.uSpinAngle, reduced ? 0 : spinAngle);
      gl.uniform1f(U.uWave, cur.wave); gl.uniform1f(U.uBurst, cur.burst);
      gl.uniform2f(U.uOffset, cur.ox, cur.oy); gl.uniform2f(U.uFrame, cur.fy, cur.fz); gl.uniform2f(U.uTilt, cur.tiltX, cur.tiltY);
      gl.uniform3fv(U.uColA, curColors[0]); gl.uniform3fv(U.uColB, curColors[1]); gl.uniform3fv(U.uColC, curColors[2]);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.POINTS, 0, count);

      // Frame rate watch: under 40 fps for two seconds drops one quality step.
      frames++;
      if (now - fpsAt >= 1000) {
        fps = Math.round((frames * 1000) / (now - fpsAt)); frames = 0; fpsAt = now;
        // Under 10 fps means the browser is throttling a hidden or background page, not a slow computer.
        if (autoQuality && fps >= 10 && fps < 40 && quality > 0) { if (!slowSince) slowSince = now; else if (now - slowSince >= 2000) { setQuality(quality - 1); slowSince = 0; } }
        else slowSince = 0;
      }
    }

    function setQuality(q) {
      quality = Math.max(0, Math.min(QUALITY.length - 1, q));
      count = QUALITY[quality];
    }

    let icon = '';
    function setState(name, wantIcon = '') {
      if (name === 'topic' && !ICONS[wantIcon]) return;
      if (!STATES[name] || (name === state && wantIcon === icon)) return;
      icon = wantIcon;
      // Start the new morph from wherever each particle is right now.
      const m = mix;
      if (m < 1) for (let i = 0; i < MAX; i++) {
        const s = seeds[i * 4] * 0.45, e = Math.min(1, Math.max(0, (m - s) / 0.55)), w = e * e * (3 - 2 * e);
        for (let j = 0; j < 3; j++) fromData[i * 4 + j] += (toData[i * 4 + j] - fromData[i * 4 + j]) * w;
        if (w >= 0.5) fromData[i * 4 + 3] = toData[i * 4 + 3];
      } else fromData.set(toData);
      state = name;
      toData = shape(name, MAX, icon);
      upload(fromBuf, fromData); upload(toBuf, toData);
      mixStart = performance.now(); mix = 0;
    }

    let paused = false;
    const onVisible = () => {
      if (document.hidden || paused) { cancelAnimationFrame(raf); running = false; }
      else if (!running) { running = true; last = performance.now(); fpsAt = last; frames = 0; raf = requestAnimationFrame(frame); }
    };
    document.addEventListener('visibilitychange', onVisible);
    // The scene leans a little toward the visitor's finger.
    const onPointer = (e) => { tiltX = (e.clientX / window.innerWidth - 0.5) * 0.12; tiltY = (e.clientY / window.innerHeight - 0.5) * 0.07; };
    window.addEventListener('pointermove', onPointer);
    window.addEventListener('pointerdown', onPointer);
    canvas.addEventListener('webglcontextlost', (e) => {
      e.preventDefault(); cancelAnimationFrame(raf); running = false;
      if (opts.onLost) opts.onLost();  // the page falls back to its plain background
    });

    raf = requestAnimationFrame(frame);
    return {
      setState,
      /** Trace a topic's line drawing ('pin', 'cap', 'mail', ...). Unknown names are ignored. */
      setTopic(name) { setState('topic', name); },
      /** 0..1 loudness of whoever is talking (visitor while listening, Cynobot while answering). */
      setLevel(v) { level = Math.max(0, Math.min(1, v || 0)); },
      setTheme(name) { themeName = name; applyColors(); },
      /** Which idle shape: 'globe', 'aurora' or 'stars' (a constellation C). */
      setIdle(style) {
        if (!IDLE_STYLES.includes(style) || style === idleStyle) return;
        idleStyle = style;
        if (state === 'idle') { const keep = state; state = ''; setState(keep); }
      },
      /** Free area for the face/ring/swirl: its centre (0 = top of screen, 1 = bottom) and height (0..1 of the screen). */
      setFrame(centre, height) {
        frameY = 1 - 2 * Math.max(0, Math.min(1, centre));
        frameZoom = Math.max(0.35, Math.min(1.15, height / 0.56));
      },
      burst() { cur.burst = 1; },
      /** Stop or restart drawing (the plain background setting, set in Cyno Control). */
      pause(on) {
        paused = Boolean(on);
        if (paused) { cancelAnimationFrame(raf); running = false; gl.clear(gl.COLOR_BUFFER_BIT); }
        else onVisible();
      },
      /** Fixed particle count (0 fewest .. 3 most). Turns the automatic step-down off. */
      setQuality(q) { autoQuality = false; setQuality(q); },
      /** Start from `q` and step down by itself if the frame rate stays low. */
      setAuto(q = 2) { autoQuality = true; slowSince = 0; setQuality(q); },
      stats() { return { fps, particles: count, quality, state, auto: autoQuality, renderer }; },
      destroy() {
        cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', onVisible);
        window.removeEventListener('pointermove', onPointer); window.removeEventListener('pointerdown', onPointer);
      },
    };
  }

  window.CynoParticles = { create, states: Object.keys(STATES), icons: Object.keys(ICONS), iconPaths: ICONS, idleStyles: IDLE_STYLES };
})();
