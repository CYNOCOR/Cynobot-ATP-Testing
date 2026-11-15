/* Cynobot's idle scene on the chest screen: a slowly turning 3D brain made of neurons.

   About 500 neurons sit on a folded cortex (two hemispheres), the cerebellum and the brainstem,
   each wired to its four nearest neighbours. Neurons fire on their own; a spike travels along a
   link and may set off the neighbour, so cascades of activity sweep across the brain like a live
   scan, with a bigger "thought wave" from one region every few seconds. A neuron rests briefly
   after firing, which keeps the cascades from taking over.

     const brain = CynoBrain.create(canvas, { density: 'full' });
     brain.show(true);  brain.setFrame(centreYpx, heightPx);  brain.setDensity('light');

   Plain 2D canvas (no 3D graphics needed). It only draws while shown, and reads the Red/Blue
   colours from /shared/theme.css. */
(function () {
  const DENSITY = { full: { cortex: 400, cerebellum: 70, stem: 30 }, light: { cortex: 240, cerebellum: 45, stem: 20 } };

  function seeded(s) { return () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646; }
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  function project(p, yaw, pitch, scale, cx, cy, t) {
    const w = Math.sin(t * 1.6 + p.y * 5 + p.x * 4) * 0.0045;
    const x0 = p.x + w, y0 = p.y + w * 0.6, z0 = p.z;
    const x1 = x0 * Math.cos(yaw) - z0 * Math.sin(yaw), z1 = x0 * Math.sin(yaw) + z0 * Math.cos(yaw);
    const y2 = y0 * Math.cos(pitch) - z1 * Math.sin(pitch), z2 = y0 * Math.sin(pitch) + z1 * Math.cos(pitch);
    const k = 1.65 / (1.65 - z2 * 0.72);
    return { x: cx + x1 * scale * k, y: cy + y2 * scale * k, z: z2, k };
  }

  function build(density) {
    const n = DENSITY[density] || DENSITY.full, rand = seeded(31415), nodes = [];
    const add = (x, y, z) => nodes.push({ x, y, z, fire: -10 });
    // cerebrum: neurons on a folded cortex (two hemispheres with a gap), fuller at the front,
    // flatter underneath; a few inside
    while (nodes.length < n.cortex) {
      const zz = rand() * 2 - 1, a = rand() * 6.283, q = Math.sqrt(1 - zz * zz);
      const dx = Math.cos(a) * q, dy = zz, dz = Math.sin(a) * q;
      const fold = 1 + 0.07 * Math.sin(dx * 13 + dy * 7) * Math.sin(dy * 11 - dz * 9);   // gyri and sulci
      const depth = rand() < 0.85 ? 0.95 + rand() * 0.05 : 0.3 + rand() * 0.6;
      const front = dx < 0 ? 1.06 : 1;
      const x = dx * 0.36 * front * fold * depth, y = dy * 0.24 * fold * depth, z = dz * 0.27 * fold * depth;
      if (Math.abs(z) < 0.02 || y > 0.13 - x * 0.1) continue;
      add(x, y - 0.03, z);
    }
    while (nodes.length < n.cortex + n.cerebellum) {   // cerebellum, tucked under the back
      const zz = rand() * 2 - 1, a = rand() * 6.283, q = Math.sqrt(1 - zz * zz), k = 0.85 + rand() * 0.15;
      add(Math.cos(a) * q * 0.12 * k + 0.21, zz * 0.07 * k + 0.14, Math.sin(a) * q * 0.16 * k);
    }
    while (nodes.length < n.cortex + n.cerebellum + n.stem) {   // brainstem
      const u = rand(), a = rand() * 6.283, r = Math.sqrt(rand()) * 0.035;
      add(0.1 + u * 0.03 + Math.cos(a) * r * 0.6, 0.12 + u * 0.18, Math.sin(a) * r);
    }
    const links = [], seen = new Set();
    nodes.forEach((p, i) => {
      nodes.map((o, j) => ({ j, d: j === i ? 9 : (o.x - p.x) ** 2 + (o.y - p.y) ** 2 + (o.z - p.z) ** 2 }))
        .sort((a, b) => a.d - b.d).slice(0, 4)
        .forEach(({ j, d }) => { const key = i < j ? i + ',' + j : j + ',' + i; if (!seen.has(key)) { seen.add(key); links.push({ a: i, b: j, len: Math.sqrt(d) }); } });
    });
    const nbr = nodes.map(() => []);
    links.forEach((l, k) => { nbr[l.a].push(k); nbr[l.b].push(k); });
    return { nodes, links, nbr, cortex: n.cortex };
  }

  function create(canvas, opts = {}) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    let W = 0, H = 0, dpr = 1, frameCy = null, frameH = null;
    let net = build(opts.density || 'full'), density = opts.density || 'full';
    let signals = [], queue = [], waves = [], nextSpont = 0, nextWave = 4;
    const rand = seeded(2718);
    let C = {};
    function colours() {
      const st = getComputedStyle(document.body), v = (n, d) => st.getPropertyValue(n).trim() || d;
      C = { acc: v('--cy-accent-rgb', '255, 42, 60'), shine: v('--cy-p3', '255, 189, 194'), grey: '205, 212, 226' };
    }
    colours();
    const themeWatch = new MutationObserver(colours);
    themeWatch.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    const rgba = (rgb, a) => `rgba(${rgb}, ${clamp(a, 0, 1).toFixed(3)})`;
    function glow(x, y, r, rgb, a) {
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, rgba(rgb, a)); g.addColorStop(1, rgba(rgb, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.283); ctx.fill();
    }
    function dot(x, y, r, col) { ctx.beginPath(); ctx.arc(x, y, r, 0, 6.283); ctx.fillStyle = col; ctx.fill(); }
    function resize() {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = canvas.width = Math.round(canvas.clientWidth * dpr) || 1;
      H = canvas.height = Math.round(canvas.clientHeight * dpr) || 1;
    }
    resize();
    addEventListener('resize', resize);

    // Spikes travel slowly (about 0.6-1 s per link) so each one can be followed by eye.
    function fire(i, t) {
      const p = net.nodes[i];
      if (!p || t - p.fire < 2.2) return;   // resting after the last spike
      p.fire = t;
      for (const k of net.nbr[i]) {
        if (rand() < 0.3) { const l = net.links[k], to = l.a === i ? l.b : l.a; queue.push({ from: i, to, t0: t, dur: 0.4 + l.len * 7 }); }
      }
    }

    function draw(t) {
      if (queue.length) { signals.push(...queue); queue = []; }
      const m = Math.min(W, H);
      // sit in the free space above the words (set by the page), else a little above centre
      const cy = frameCy != null ? frameCy * dpr : H * 0.38;
      const sc = frameH != null ? Math.min(m * 1.15, frameH * dpr * 1.9) : m * 1.15;
      const cx = W * 0.5, yaw = Math.sin(t * 0.2) * 0.45, pitch = 0.1 + Math.sin(t * 0.17) * 0.06;   // mostly a side view
      const P = net.nodes.map((p) => project(p, yaw, pitch, sc, cx, cy, t));
      if (t > nextSpont) { fire(Math.floor(rand() * net.nodes.length), t); nextSpont = t + 0.12 + rand() * 0.3; }
      if (t > nextWave) {   // a bigger wave spreading out from one region of the cortex
        const c = net.nodes[Math.floor(rand() * net.cortex)];
        net.nodes.forEach((p, i) => { const d = Math.hypot(p.x - c.x, p.y - c.y, p.z - c.z); if (d < 0.12) waves.push({ i, t: t + d * 6 }); });
        nextWave = t + 9 + rand() * 6;
      }
      waves = waves.filter((w) => { if (t < w.t) return true; fire(w.i, t); return false; });

      ctx.clearRect(0, 0, W, H);
      ctx.lineWidth = 0.8 * dpr;
      ctx.strokeStyle = rgba(C.acc, 0.13);
      ctx.beginPath();
      for (const l of net.links) { const A = P[l.a], B = P[l.b]; ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); }
      ctx.stroke();
      signals = signals.filter((s) => {
        const u = (t - s.t0) / s.dur;
        if (u >= 1) { fire(s.to, t); return false; }
        const A = P[s.from], B = P[s.to], x = A.x + (B.x - A.x) * u, y = A.y + (B.y - A.y) * u, u0 = Math.max(0, u - 0.35);
        ctx.beginPath(); ctx.moveTo(A.x + (B.x - A.x) * u0, A.y + (B.y - A.y) * u0); ctx.lineTo(x, y);
        ctx.lineWidth = 1.8 * dpr; ctx.strokeStyle = rgba(C.acc, 0.85); ctx.stroke();
        dot(x, y, 1.8 * dpr * A.k, rgba(C.shine, 1));
        return true;
      });
      const order = P.map((p, i) => i).sort((a, b) => P[a].z - P[b].z);
      for (const i of order) {
        const p = P[i], since = t - net.nodes[i].fire, f = since >= 0 ? Math.exp(-since * 1.6) : 0, depth = clamp(0.55 + p.z * 1.4, 0.35, 1.2);
        if (f > 0.04) glow(p.x, p.y, (10 + f * 18) * dpr * p.k, C.acc, 0.55 * f);
        dot(p.x, p.y, (1.3 + f * 2.2) * dpr * p.k, f > 0.04 ? rgba(C.shine, 0.5 + f * 0.5) : rgba(C.grey, 0.45 * depth));
      }
    }

    let raf = 0, running = false, shown = false, stopTimer = 0, frames = 0, fps = 0, fpsAt = performance.now();
    function loop(now) {
      if (!running) return;
      if (!document.hidden) {
        draw(now / 1000);
        frames++;
        if (now - fpsAt > 1000) { fps = Math.round((frames * 1000) / (now - fpsAt)); frames = 0; fpsAt = now; }
      }
      raf = requestAnimationFrame(loop);
    }
    return {
      /** Fade in (true) or out (false); it stops drawing once it has faded out. */
      show(on) {
        on = Boolean(on);
        if (on === shown) return;
        shown = on;
        canvas.classList.toggle('on', on);
        clearTimeout(stopTimer);
        if (on && !running) { running = true; resize(); raf = requestAnimationFrame(loop); }
        if (!on) stopTimer = setTimeout(() => { running = false; cancelAnimationFrame(raf); ctx.clearRect(0, 0, W, H); }, 1000);
      },
      /** Where the brain sits: the centre of the free space and its height (CSS pixels). */
      setFrame(centreY, height) { frameCy = centreY; frameH = height; },
      /** 'full' (about 500 neurons) or 'light' (about 300). */
      setDensity(d) {
        if (!DENSITY[d] || d === density) return;
        density = d; net = build(d); signals = []; queue = []; waves = [];
      },
      stats: () => ({ fps, neurons: net.nodes.length, shown }),
      destroy() { running = false; cancelAnimationFrame(raf); themeWatch.disconnect(); removeEventListener('resize', resize); },
    };
  }

  window.CynoBrain = { create };
})();
