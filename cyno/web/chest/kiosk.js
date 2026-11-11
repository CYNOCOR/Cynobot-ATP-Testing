/* Locked chest screen. Active only when Cyno Control opened this page in the kiosk window
   (address ends in ?kiosk=1). The browser itself has no close button in that mode.
   Staff way out, hidden from visitors: tap the CYNOBOT logo three times, then press and
   hold it for 10 seconds (a countdown shows it is working). That opens the PIN pad, and
   the right PIN closes the window. The PIN is checked by the server, never stored here. */
(function () {
  if (new URLSearchParams(location.search).get('kiosk') !== '1') return;

  const css = document.createElement('style');
  css.textContent = `
    .brand { position: relative; padding: 14px 18px; margin: -14px -18px; touch-action: none; -webkit-touch-callout: none; }
    .k-hold { position: fixed; top: 64px; left: 40px; z-index: 60; display: flex; align-items: center; gap: 12px; padding: 10px 18px 10px 12px;
      border-radius: 999px; background: var(--glass); border: 1px solid var(--glass-edge); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
      font-size: 15px; font-weight: 600; color: var(--text); animation: rise-in 0.3s var(--spring) both; pointer-events: none; }
    .k-hold svg { width: 38px; height: 38px; transform: rotate(-90deg); }
    .k-hold circle { fill: none; stroke-width: 4; }
    .k-hold .track { stroke: rgba(255, 255, 255, 0.14); }
    .k-hold .fill { stroke: var(--accent); stroke-linecap: round; stroke-dasharray: 100.5; stroke-dashoffset: 100.5; }
    .k-hold b { font-variant-numeric: tabular-nums; min-width: 1.4em; text-align: center; font-size: 18px; }
    .k-pad { position: fixed; inset: 0; z-index: 50; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px;
      background: rgba(6, 3, 4, 0.86); backdrop-filter: blur(26px); -webkit-backdrop-filter: blur(26px); }
    .k-pad h2 { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
    .k-pad p { font-size: 16px; color: var(--muted); min-height: 1.3em; text-align: center; }
    .k-pad p.bad { color: #ffb4b4; }
    .k-dots { display: flex; gap: 12px; height: 18px; }
    .k-dots i { width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--muted); }
    .k-dots i.on { background: var(--text); border-color: var(--text); }
    .k-keys { display: grid; grid-template-columns: repeat(3, 84px); gap: 14px; }
    .k-keys button { appearance: none; cursor: pointer; font: inherit; font-size: 28px; font-weight: 600; color: var(--text);
      height: 84px; border-radius: 50%; background: var(--glass); border: 1px solid var(--glass-edge); }
    .k-keys button:active { background: rgba(255, 255, 255, 0.18); }
    .k-keys button.small { font-size: 15px; color: var(--muted); }
    .k-keys button:disabled { opacity: 0.35; }
    .k-pad.shake .k-dots { animation: g-shake 0.35s; }
    html, body { touch-action: manipulation; overscroll-behavior: none; }
  `;
  document.head.appendChild(css);

  // Keep visitors inside the page: no right-click menu, drag, zoom gestures or text selection.
  ['contextmenu', 'dragstart', 'selectstart', 'gesturestart'].forEach((ev) => document.addEventListener(ev, (e) => e.preventDefault()));
  document.addEventListener('wheel', (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

  let pad = null, pin = '', idle = null, busy = false, waitTimer = null;

  function closePad() { clearTimeout(idle); clearInterval(waitTimer); if (pad) pad.remove(); pad = null; pin = ''; busy = false; }
  function touch() { clearTimeout(idle); idle = setTimeout(closePad, 20000); }
  function say(text, bad) { const p = pad.querySelector('p'); p.textContent = text; p.classList.toggle('bad', Boolean(bad)); }
  function dots() { pad.querySelectorAll('.k-dots i').forEach((d, i) => d.classList.toggle('on', i < pin.length)); }
  function freeze(on) { pad.querySelectorAll('.k-keys button[data-k]').forEach((b) => (b.disabled = on)); }

  function lockOut(secs) {
    freeze(true);
    let left = secs;
    const show = () => say(`Too many tries. Wait ${left} s.`, true);
    show();
    clearInterval(waitTimer);
    waitTimer = setInterval(() => { if (--left <= 0) { clearInterval(waitTimer); freeze(false); say('Enter the staff PIN'); } else show(); }, 1000);
  }

  async function submit() {
    if (busy || pin.length < 4) return;
    busy = true;
    let r = null;
    try { r = await (await fetch('/api/kiosk/unlock', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }) })).json(); } catch (e) {}
    busy = false; pin = '';
    if (!pad) return;
    dots();
    if (r && r.ok) { say('Unlocked. Closing…'); freeze(true); clearTimeout(idle); return; }
    pad.classList.remove('shake'); void pad.offsetWidth; pad.classList.add('shake');
    if (r && r.wait) lockOut(r.wait);
    else say(r ? `Wrong PIN. ${r.left} ${r.left === 1 ? 'try' : 'tries'} left.` : 'Could not reach Cynobot.', true);
  }

  function openPad() {
    if (pad) return;
    pad = document.createElement('div');
    pad.className = 'k-pad';
    pad.innerHTML = `<h2>Staff only</h2><p>Enter the staff PIN</p>
      <div class="k-dots">${'<i></i>'.repeat(8)}</div>
      <div class="k-keys">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<button data-k="${n}">${n}</button>`).join('')}
        <button class="small" data-cancel>Cancel</button><button data-k="0">0</button><button class="small" data-k="ok">OK</button></div>`;
    document.body.appendChild(pad);
    pad.addEventListener('pointerdown', touch);
    pad.querySelector('[data-cancel]').onclick = closePad;
    pad.querySelectorAll('[data-k]').forEach((b) => (b.onclick = () => {
      if (b.dataset.k === 'ok') return submit();
      if (pin.length < 8) { pin += b.dataset.k; dots(); }
    }));
    touch();
  }
  // ---- hidden staff gesture on the logo: 3 quick taps, then hold for 10 seconds ----
  const logo = document.querySelector('.brand');
  const HOLD_MS = 10000, TAP_MS = 400, TAP_GAP_MS = 1200, ARMED_MS = 4000;
  let taps = 0, lastTap = 0, downAt = 0, armedUntil = 0, holdTick = null, holdBox = null;

  function stopHold() {
    clearInterval(holdTick); holdTick = null;
    if (holdBox) holdBox.remove();
    holdBox = null;
  }
  function startHold() {
    stopHold();
    const began = Date.now();
    holdBox = document.createElement('div');
    holdBox.className = 'k-hold';
    holdBox.innerHTML = '<svg viewBox="0 0 38 38"><circle class="track" cx="19" cy="19" r="16"/><circle class="fill" cx="19" cy="19" r="16"/></svg><span>Keep holding</span><b>10</b>';
    document.body.appendChild(holdBox);
    const draw = () => {
      const gone = Date.now() - began;
      holdBox.querySelector('b').textContent = Math.max(0, Math.ceil((HOLD_MS - gone) / 1000));
      holdBox.querySelector('.fill').style.strokeDashoffset = 100.5 * (1 - Math.min(1, gone / HOLD_MS));
      if (gone >= HOLD_MS) { stopHold(); taps = 0; armedUntil = 0; openPad(); }
    };
    draw();
    holdTick = setInterval(draw, 100);
  }
  if (logo) {
    logo.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      downAt = Date.now();
      if (downAt < armedUntil && !pad) startHold();  // the hold after three taps
    });
    const up = () => {
      const now = Date.now();
      if (holdTick) { stopHold(); taps = 0; armedUntil = 0; return; }  // let go too early
      if (!downAt || now - downAt > TAP_MS) { taps = 0; downAt = 0; return; }
      taps = now - lastTap < TAP_GAP_MS ? taps + 1 : 1;
      lastTap = now; downAt = 0;
      if (taps >= 3) { taps = 0; armedUntil = now + ARMED_MS; }
    };
    logo.addEventListener('pointerup', up);
    logo.addEventListener('pointercancel', () => { stopHold(); taps = 0; });
    logo.addEventListener('pointerleave', () => { if (holdTick) { stopHold(); taps = 0; armedUntil = 0; } });
  }
  window.CynoKiosk = { openPad };  // for tests
})();
