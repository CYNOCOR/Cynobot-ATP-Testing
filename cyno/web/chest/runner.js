/* Cyno Run: a little endless runner for the chest screen (like the browser's dino game).

   Cynobot rolls along a glowing circuit floor. Tap to jump (hold for a higher jump), swipe
   down or tap the bottom of the screen to duck under drones, and grab batteries for points.
   Easy has 3 lives and starts slow; Normal is one crash and out.

     const run = CynoRunner.start(element, { level: 'easy', sound: true, onCrash, onOver });
     run.pause(); run.resume(); const result = run.stop();   // { score, metres, batteries }

   Everything is drawn in code (no pictures to download) in the shared theme colours, on a
   plain 2D canvas so it stays light on a laptop's built-in graphics. */
(function () {
  const H = 400;                     // world height in units; width follows the screen shape
  const GROUND = 318;                // floor line
  const ROBOT_X = 120;
  const STAND_H = 78, DUCK_H = 44;   // robot height standing / ducking
  const GRAVITY = 2500, JUMP_V = 840, HOLD_SECS = 0.22;
  const LEVELS = {
    easy: { lives: 3, speed: 250, accel: 5, max: 520, droneAfter: 220 },
    normal: { lives: 1, speed: 320, accel: 8, max: 700, droneAfter: 90 },
  };

  function start(el, opts = {}) {
    const L = LEVELS[opts.level] || LEVELS.easy;
    const canvas = document.createElement('canvas');
    canvas.className = 'run-canvas';
    canvas.setAttribute('aria-label', 'Cyno Run game. Tap to jump, swipe down to duck.');
    el.appendChild(canvas);
    const ctx = canvas.getContext('2d');
    let W = 700, scale = 1, dpr = 1;

    // ---- colours from the shared theme (Red or Blue) ----
    let C = {};
    function readColours() {
      const st = getComputedStyle(document.body);
      const v = (n, d) => (st.getPropertyValue(n) || '').trim() || d;
      C = {
        accent: v('--cy-accent', '#ff2a3c'), rgb: v('--cy-accent-rgb', '255, 42, 60'), shine: v('--cy-p3', '255, 189, 194'),
        text: v('--cy-text', '#fcecef'), textRgb: v('--cy-text-rgb', '252, 236, 239'), bg1: v('--cy-bg1', '#260508'), bg2: v('--cy-bg2', '#120204'), bg3: v('--cy-bg3', '#060102'),
        panel: v('--cy-panel-rgb', '28, 8, 11'), font: v('--cy-font', 'system-ui, sans-serif'),
      };
    }
    readColours();
    const themeWatch = new MutationObserver(readColours);
    themeWatch.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    const a = (alpha) => `rgba(${C.rgb}, ${alpha})`;
    // Each kind of thing has its own colour so it reads at a glance: Cynobot in the theme
    // colour, obstacles amber (danger), batteries green (collect), scenery soft grey.
    const HAZARD = '255, 184, 77', PICKUP = '140, 255, 130', SCENERY = '215, 222, 235';
    const rgba = (rgb, alpha) => `rgba(${rgb}, ${alpha})`;

    function resize() {
      const r = el.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.max(1, Math.round(r.width * dpr));
      canvas.height = Math.max(1, Math.round(r.height * dpr));
      scale = canvas.height / H;
      W = canvas.width / scale;
    }
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    // ---- sound: tiny bleeps made on the spot ----
    let audio = null;
    function beep(kind) {
      if (!opts.sound) return;
      try {
        audio = audio || new (window.AudioContext || window.webkitAudioContext)();
        if (audio.state === 'suspended') audio.resume();
        const t = audio.currentTime, o = audio.createOscillator(), g = audio.createGain();
        o.connect(g); g.connect(audio.destination);
        const set = { jump: ['square', 520, 820, 0.1, 0.05], battery: ['triangle', 880, 1480, 0.14, 0.08], crash: ['sawtooth', 240, 50, 0.38, 0.07], go: ['triangle', 660, 660, 0.12, 0.06] }[kind];
        o.type = set[0]; o.frequency.setValueAtTime(set[1], t); o.frequency.exponentialRampToValueAtTime(set[2], t + set[3]);
        g.gain.setValueAtTime(set[4], t); g.gain.exponentialRampToValueAtTime(0.0001, t + set[3]);
        o.start(t); o.stop(t + set[3] + 0.02);
      } catch (e) {}
    }

    // ---- game state ----
    const robot = { y: GROUND, vy: 0, onGround: true, ducking: false, holding: false, holdT: 0, wheel: 0, blink: 0, hurt: 0 };
    let mode = 'ready';                // ready | count | run | paused | crashed | over
    let speed = L.speed, travelled = 0, batteries = 0, lives = L.lives;
    let obstacles = [], pickups = [], sparks = [], nextGap = 520, countdown = 0, crashT = 0, clock = 0;
    let raf = 0, last = performance.now();

    const metres = () => Math.floor(travelled / 40);
    const score = () => metres() + batteries * 10;
    const result = () => ({ score: score(), metres: metres(), batteries });

    // ---- spawning ----
    const rand = (lo, hi) => lo + Math.random() * (hi - lo);
    function spawn() {
      const x = W + 40;
      const drones = metres() > L.droneAfter;
      const roll = Math.random();
      if (drones && roll < 0.25) {
        obstacles.push({ kind: 'drone', x, w: 62, h: 26, y: GROUND - DUCK_H - 6 - 26, spin: 0 });  // duck under it
      } else if (roll < 0.55) {
        const h = rand(34, 56);
        obstacles.push({ kind: 'bolts', x, w: rand(30, 44), h, y: GROUND - h });
      } else if (roll < 0.8) {
        obstacles.push({ kind: 'cable', x, w: 58, h: 30, y: GROUND - 30 });
      } else {
        obstacles.push({ kind: 'cone', x, w: 32, h: 50, y: GROUND - 50 });
      }
      if (Math.random() < 0.55) {  // a battery between this obstacle and the next
        const high = Math.random() < 0.6;
        pickups.push({ x: x + rand(170, 260), y: high ? GROUND - 140 : GROUND - 34, t: Math.random() * 6 });
      }
      // The gap must leave room to land and jump again: about one jump's airtime plus a bit.
      const air = (2 * JUMP_V) / GRAVITY;
      nextGap = speed * rand(air + 0.55, air + 1.5);
    }

    // ---- controls ----
    let downAt = null;
    function press(yFrac) {
      if (audio && audio.state === 'suspended') audio.resume();
      if (mode === 'ready') { mode = 'count'; countdown = 3; beep('go'); return; }
      if (mode !== 'run') return;
      if (yFrac > 0.72) { duck(true); return; }  // the bottom of the screen ducks
      jump();
    }
    function jump() {
      if (!robot.onGround || robot.ducking) return;
      robot.vy = -JUMP_V; robot.onGround = false; robot.holding = true; robot.holdT = 0;
      beep('jump');
    }
    function duck(on) {
      robot.ducking = on && mode === 'run';
      if (robot.ducking && !robot.onGround) robot.vy = Math.max(robot.vy, 600);  // drop fast
    }
    canvas.addEventListener('pointerdown', (e) => {
      const r = canvas.getBoundingClientRect();
      downAt = { y: e.clientY, id: e.pointerId };
      try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
      press((e.clientY - r.top) / r.height);
      e.preventDefault();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (downAt && e.clientY - downAt.y > 40 && mode === 'run') duck(true);  // swipe down
    });
    const release = () => { downAt = null; robot.holding = false; duck(false); };
    canvas.addEventListener('pointerup', release);
    canvas.addEventListener('pointercancel', release);
    function onKey(e) {
      if (e.repeat) return;
      if (e.code === 'Space' || e.code === 'ArrowUp') { press(0.3); e.preventDefault(); }
      if (e.code === 'ArrowDown') { if (mode === 'run') duck(true); e.preventDefault(); }
    }
    function onKeyUp(e) {
      if (e.code === 'Space' || e.code === 'ArrowUp') robot.holding = false;
      if (e.code === 'ArrowDown') duck(false);
    }
    window.addEventListener('keydown', onKey);
    window.addEventListener('keyup', onKeyUp);

    // ---- one frame ----
    function update(dt) {
      clock += dt;
      robot.blink -= dt;
      if (robot.blink < -3 - Math.random() * 3) robot.blink = 0.12;
      if (mode === 'count') {
        countdown -= dt;
        if (countdown <= 0) { mode = 'run'; beep('go'); }
        return;
      }
      if (mode === 'crashed') {
        crashT -= dt;
        sparkStep(dt);
        if (crashT <= 0) {
          if (lives > 0) { mode = 'count'; countdown = 2; robot.hurt = 2.2; }
          else { mode = 'over'; if (opts.onOver) opts.onOver(result()); }
        }
        return;
      }
      if (mode !== 'run') return;

      speed = Math.min(L.max, speed + L.accel * dt);
      const dx = speed * dt;
      travelled += dx;
      robot.wheel += dx / 14;
      robot.hurt = Math.max(0, robot.hurt - dt);

      // jump physics: holding the tap keeps lifting a little longer
      if (!robot.onGround) {
        let g = GRAVITY;
        if (robot.holding && robot.vy < 0 && robot.holdT < HOLD_SECS) { g *= 0.45; robot.holdT += dt; }
        if (robot.ducking) g *= 2.2;
        robot.vy += g * dt;
        robot.y += robot.vy * dt;
        if (robot.y >= GROUND) { robot.y = GROUND; robot.vy = 0; robot.onGround = true; }
      }

      nextGap -= dx;
      if (nextGap <= 0) spawn();
      obstacles.forEach((o) => { o.x -= dx; if (o.kind === 'drone') o.spin += dt * 30; });
      pickups.forEach((p) => { p.x -= dx; p.t += dt; });
      obstacles = obstacles.filter((o) => o.x + o.w > -60);
      pickups = pickups.filter((p) => p.x > -60 && !p.got);
      sparkStep(dt);

      // collisions (a forgiving box, a bit smaller than the drawing)
      const rh = robot.ducking ? DUCK_H : STAND_H;
      const box = { l: ROBOT_X - 22, r: ROBOT_X + 22, t: robot.y - rh + 8, b: robot.y - 4 };
      for (const p of pickups) {
        if (p.x > box.l - 14 && p.x < box.r + 14 && p.y > box.t - 16 && p.y < box.b + 16) {
          p.got = true; batteries++; beep('battery'); burst(p.x, p.y, 10, 0.9, PICKUP);
        }
      }
      if (robot.hurt > 0) return;
      for (const o of obstacles) {
        const pad = o.kind === 'drone' ? 4 : 6;
        if (box.r > o.x + pad && box.l < o.x + o.w - pad && box.b > o.y + pad && box.t < o.y + o.h - pad) {
          crash(o); break;
        }
      }
    }
    function crash(o) {
      lives--;
      mode = 'crashed'; crashT = lives > 0 ? 0.9 : 1.1;
      robot.holding = false; robot.ducking = false;
      beep('crash');
      burst(ROBOT_X + 20, robot.y - 40, 22, 1.6, HAZARD);
      obstacles = obstacles.filter((x) => x !== o);
      if (lives > 0 && opts.onCrash) opts.onCrash(lives);
    }
    function burst(x, y, n, power, rgb) {
      for (let i = 0; i < n; i++) {
        const ang = Math.random() * Math.PI * 2, v = rand(80, 260) * power;
        sparks.push({ x, y, vx: Math.cos(ang) * v, vy: Math.sin(ang) * v - 60, life: rand(0.35, 0.8), rgb });
      }
    }
    function sparkStep(dt) {
      sparks.forEach((s) => { s.x += s.vx * dt; s.y += s.vy * dt; s.vy += 600 * dt; s.life -= dt; });
      sparks = sparks.filter((s) => s.life > 0);
    }

    // ---- drawing ----
    function draw() {
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      // sky: the face's visor glow
      ctx.fillStyle = '#060709'; ctx.fillRect(0, 0, W, H);
      const sky = ctx.createRadialGradient(W / 2, GROUND, 10, W / 2, GROUND, Math.max(W, H) * 0.7);
      sky.addColorStop(0, a(0.10)); sky.addColorStop(1, a(0));   // a faint theme glow along the horizon
      ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
      drawSkyline(travelled * 0.12, 0.16, 150, 7);
      drawSkyline(travelled * 0.3, 0.3, 95, 13);
      drawFloor();
      pickups.forEach(drawBattery);
      obstacles.forEach(drawObstacle);
      drawRobot();
      sparks.forEach((s) => { ctx.fillStyle = rgba(s.rgb || C.shine, Math.min(1, s.life * 2)); ctx.fillRect(s.x - 2, s.y - 2, 4, 4); });
      drawHud();
    }

    // A circuit-board city: towers with lit windows and traces, repeating as it scrolls.
    function drawSkyline(offset, alpha, maxH, seed) {
      const span = 900, base = GROUND - 2;
      ctx.save();
      ctx.strokeStyle = rgba(SCENERY, alpha * 0.75); ctx.fillStyle = rgba(SCENERY, alpha * 0.08); ctx.lineWidth = 1.5;
      const startTile = Math.floor(offset / span) - 1;
      for (let tile = startTile; tile < startTile + Math.ceil(W / span) + 3; tile++) {
        let x = tile * span - offset;
        let r = seed * 9301 + tile * 49297;
        const rnd = () => ((r = (r * 9301 + 49297) % 233280) / 233280);
        while (x < (tile + 1) * span - offset) {
          const w = 40 + rnd() * 70, h = maxH * (0.35 + rnd() * 0.65);
          ctx.beginPath(); ctx.rect(x, base - h, w, h); ctx.fill(); ctx.stroke();
          for (let wy = base - h + 12; wy < base - 10; wy += 16) {   // windows
            for (let wx = x + 8; wx < x + w - 8; wx += 14) if (rnd() < 0.35) ctx.fillRect(wx, wy, 5, 5);
          }
          if (rnd() < 0.5) { ctx.beginPath(); ctx.moveTo(x + w / 2, base - h); ctx.lineTo(x + w / 2, base - h - 18); ctx.stroke();
            ctx.beginPath(); ctx.arc(x + w / 2, base - h - 21, 3, 0, 7); ctx.stroke(); }
          x += w + 10 + rnd() * 40;
        }
      }
      ctx.restore();
    }
    function drawFloor() {
      ctx.save();
      ctx.shadowColor = a(0.6); ctx.shadowBlur = 10;
      ctx.strokeStyle = rgba(SCENERY, 0.85); ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.moveTo(0, GROUND); ctx.lineTo(W, GROUND); ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = rgba(SCENERY, 0.12); ctx.lineWidth = 1.2;
      const step = 46, off = travelled % step;
      for (let x = -off; x < W + step; x += step) {   // grid lines rushing past, fanning out
        ctx.beginPath(); ctx.moveTo(x, GROUND); ctx.lineTo(W / 2 + (x - W / 2) * 1.9, H); ctx.stroke();
      }
      for (const y of [GROUND + 22, GROUND + 50]) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
      ctx.restore();
    }
    function glowStroke(width, rgb = C.rgb) {
      ctx.strokeStyle = `rgb(${rgb})`; ctx.lineWidth = width; ctx.shadowColor = rgba(rgb, 0.85); ctx.shadowBlur = 10;
      ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    }
    function drawObstacle(o) {
      ctx.save();
      glowStroke(3, HAZARD);
      ctx.fillStyle = `rgba(${C.panel}, 0.9)`;
      if (o.kind === 'bolts') {   // a stack of hex nuts
        const n = Math.max(2, Math.round(o.h / 18)), hh = o.h / n;
        for (let i = 0; i < n; i++) {
          const cy = o.y + o.h - hh * (i + 0.5), cx = o.x + o.w / 2 + (i % 2 ? 3 : -3), r = Math.min(o.w / 2, hh * 0.62);
          ctx.beginPath();
          for (let k = 0; k < 6; k++) { const t = Math.PI / 3 * k + Math.PI / 6; ctx.lineTo(cx + Math.cos(t) * r, cy + Math.sin(t) * r * 0.78); }
          ctx.closePath(); ctx.fill(); ctx.stroke();
          ctx.beginPath(); ctx.arc(cx, cy, r * 0.32, 0, 7); ctx.stroke();
        }
      } else if (o.kind === 'cable') {   // a springy coil of cable
        ctx.beginPath(); ctx.ellipse(o.x + o.w / 2, o.y + o.h * 0.6, o.w / 2, o.h * 0.42, 0, 0, 7); ctx.fill();
        for (let i = 0; i < 4; i++) { ctx.beginPath(); ctx.ellipse(o.x + o.w / 2, o.y + o.h * 0.6 - i * 4, o.w / 2 - i * 5, o.h * 0.38 - i * 3, 0, 0, 7); ctx.stroke(); }
        ctx.beginPath(); ctx.moveTo(o.x + o.w - 4, o.y + o.h * 0.5); ctx.quadraticCurveTo(o.x + o.w + 14, o.y - 6, o.x + o.w + 4, o.y + 2); ctx.stroke();
      } else if (o.kind === 'cone') {
        ctx.beginPath(); ctx.moveTo(o.x + o.w / 2, o.y); ctx.lineTo(o.x + o.w, o.y + o.h - 6); ctx.lineTo(o.x, o.y + o.h - 6); ctx.closePath(); ctx.fill(); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(o.x - 5, o.y + o.h - 3); ctx.lineTo(o.x + o.w + 5, o.y + o.h - 3); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(o.x + o.w * 0.3, o.y + o.h * 0.5); ctx.lineTo(o.x + o.w * 0.7, o.y + o.h * 0.5); ctx.stroke();
      } else {   // a drone with spinning rotors and a little red eye
        const cx = o.x + o.w / 2, cy = o.y + o.h * 0.65;
        ctx.beginPath(); ctx.roundRect(o.x + 12, cy - 8, o.w - 24, 16, 8); ctx.fill(); ctx.stroke();
        for (const side of [-1, 1]) {
          const rx = cx + side * (o.w / 2 - 6);
          ctx.beginPath(); ctx.moveTo(cx + side * 12, cy - 4); ctx.lineTo(rx, cy - 12); ctx.stroke();
          const s = Math.abs(Math.sin(o.spin + side));
          ctx.beginPath(); ctx.ellipse(rx, cy - 14, 15 * s + 3, 3, 0, 0, 7); ctx.stroke();
        }
        ctx.shadowBlur = 14; ctx.fillStyle = `rgb(${HAZARD})`; ctx.beginPath(); ctx.arc(cx, cy + 1, 3.5, 0, 7); ctx.fill();
      }
      ctx.restore();
    }
    function drawBattery(p) {
      const bob = Math.sin(p.t * 4) * 4, x = p.x - 10, y = p.y - 15 + bob;
      ctx.save();
      glowStroke(2.5, PICKUP);
      ctx.fillStyle = rgba(PICKUP, 0.16);
      ctx.beginPath(); ctx.roundRect(x, y, 20, 30, 4); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.roundRect(x + 6, y - 5, 8, 5, 1.5); ctx.stroke();
      ctx.fillStyle = `rgb(${PICKUP})`; ctx.shadowBlur = 8;
      ctx.beginPath(); ctx.moveTo(x + 12, y + 6); ctx.lineTo(x + 6, y + 16); ctx.lineTo(x + 10, y + 16); ctx.lineTo(x + 8, y + 25); ctx.lineTo(x + 14, y + 13); ctx.lineTo(x + 10, y + 13); ctx.closePath(); ctx.fill();
      ctx.restore();
    }
    // Cynobot: a round head with the head screen's ring eyes, a body, a wheel and an antenna.
    function drawRobot() {
      if (robot.hurt > 0 && Math.floor(robot.hurt * 10) % 2 === 0) return;  // blink while safe after a crash
      const duck = robot.ducking && robot.onGround;
      const x = ROBOT_X, by = robot.y;
      const squash = duck ? 0.56 : 1;
      ctx.save();
      glowStroke(3);
      ctx.fillStyle = `rgba(${C.panel}, 0.95)`;
      // wheel
      const wr = 13, wy = by - wr;
      ctx.beginPath(); ctx.arc(x, wy, wr, 0, 7); ctx.fill(); ctx.stroke();
      for (let k = 0; k < 3; k++) { const t = robot.wheel + k * 2.094; ctx.beginPath(); ctx.moveTo(x, wy); ctx.lineTo(x + Math.cos(t) * wr * 0.8, wy + Math.sin(t) * wr * 0.8); ctx.stroke(); }
      // body
      const bodyH = 24 * squash, bodyTop = wy - wr - bodyH + 4;
      ctx.beginPath(); ctx.roundRect(x - 17, bodyTop, 34, bodyH, 9); ctx.fill(); ctx.stroke();
      // head
      const hw = 52, hh = 38 * (duck ? 0.82 : 1), hx = x - hw / 2 + 4, hy = bodyTop - hh + 3;
      ctx.beginPath(); ctx.roundRect(hx, hy, hw, hh, 15); ctx.fill(); ctx.stroke();
      // antenna (its tip blinks)
      ctx.beginPath(); ctx.moveTo(hx + hw / 2, hy); ctx.lineTo(hx + hw / 2 + 4, hy - 13); ctx.stroke();
      ctx.fillStyle = Math.sin(clock * 6) > 0 ? C.accent : `rgb(${C.shine})`;
      ctx.beginPath(); ctx.arc(hx + hw / 2 + 4, hy - 15, 3.5, 0, 7); ctx.fill();
      // eyes: rings with dark pupils and a white shine, like the head screen
      const crashed = mode === 'crashed' || mode === 'over';
      const look = robot.onGround ? 0 : -2.5;
      for (const ex of [hx + 15, hx + hw - 13]) {
        const ey = hy + hh / 2 + 1;
        ctx.shadowBlur = 8;
        if (crashed) {   // surprised: wide rings, tiny pupils
          ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(ex, ey, 8.5, 0, 7); ctx.stroke();
          ctx.fillStyle = `rgb(${C.shine})`; ctx.beginPath(); ctx.arc(ex, ey, 2, 0, 7); ctx.fill();
        } else if (robot.blink > 0 || duck) {   // blink, or squinting while ducking
          ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(ex - 7, ey); ctx.lineTo(ex + 7, ey); ctx.stroke();
        } else {
          ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(ex, ey, 7.5, 0, 7); ctx.stroke();
          ctx.shadowBlur = 0; ctx.fillStyle = C.bg3; ctx.beginPath(); ctx.arc(ex + 1, ey + look, 4.2, 0, 7); ctx.fill();
          ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(ex - 0.6, ey + look - 1.6, 1.6, 0, 7); ctx.fill();
        }
      }
      ctx.restore();
    }
    function drawHud() {
      ctx.save();
      ctx.font = `600 22px ${C.font}`; ctx.textBaseline = 'top';
      ctx.fillStyle = C.text; ctx.shadowColor = a(0.6); ctx.shadowBlur = 8;
      ctx.fillText(`${metres()} m`, 22, 18);
      ctx.font = `500 17px ${C.font}`; ctx.fillStyle = rgba(PICKUP, 0.95);
      ctx.fillText(`${batteries} ${batteries === 1 ? 'battery' : 'batteries'}   ·   ${score()} points`, 22, 48);
      if (L.lives > 1) {   // lives as little batteries, top right
        for (let i = 0; i < L.lives; i++) {
          const x = W - 30 - i * 30, y = 20;
          ctx.strokeStyle = C.accent; ctx.lineWidth = 2; ctx.fillStyle = i < lives ? C.accent : 'transparent';
          ctx.beginPath(); ctx.roundRect(x, y, 18, 26, 3); ctx.fill(); ctx.stroke();
          ctx.beginPath(); ctx.rect(x + 5, y - 4, 8, 4); ctx.stroke();
        }
      }
      ctx.textAlign = 'center'; ctx.fillStyle = C.text;
      if (mode === 'ready') {
        ctx.font = `600 34px ${C.font}`; ctx.fillText('Tap to start', W / 2, H * 0.3);
        ctx.font = `400 18px ${C.font}`; ctx.fillStyle = `rgba(${C.textRgb}, 0.7)`;
        ctx.fillText('Tap to jump · hold to jump higher · swipe down or tap low to duck', W / 2, H * 0.3 + 46);
      } else if (mode === 'count' || mode === 'paused') {
        ctx.font = `600 64px ${C.font}`;
        ctx.fillText(mode === 'paused' ? 'Paused' : String(Math.max(1, Math.ceil(countdown))), W / 2, H * 0.28);
      }
      ctx.restore();
    }

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (!document.hidden) { update(dt); draw(); }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame((t) => { last = t; frame(t); });

    let stopped = false;
    return {
      /** Freeze the run (a question mid-game). */
      pause() { if (mode === 'run' || mode === 'count') { mode = 'paused'; robot.holding = false; robot.ducking = false; } },
      /** Carry on after a 3-2-1. */
      resume() { if (mode === 'paused') { mode = 'count'; countdown = 3; last = performance.now(); } },
      /** End it (time up, or the game is closed); returns the result so far. */
      stop() {
        if (!stopped) {
          stopped = true; cancelAnimationFrame(raf); ro.disconnect(); themeWatch.disconnect();
          window.removeEventListener('keydown', onKey); window.removeEventListener('keyup', onKeyUp);
          try { if (audio) audio.close(); } catch (e) {}
        }
        return result();
      },
      state: () => ({ mode, lives, speed: Math.round(speed), ...result() }),
    };
  }

  window.CynoRunner = { start };
})();
