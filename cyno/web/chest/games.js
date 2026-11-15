/* Chest-screen games. Runs beside the conversation: the voice link stays up while a game
   is open, tap games work with no internet, and Word Chain is played by voice.
   Settings, riddles, the degree quiz and puzzle pictures come from /api/games
   (edited in Cyno Control > Games). Each game ends at the time limit, and a tap game
   closes after a while with no touch, so the robot is free for the next visitor. */
(function () {
  const $ = (id) => document.getElementById(id);
  const root = $('games');
  const loadedAt = Date.now();
  let cfg = null, state = {}, rev = null, lastRequest = 0;
  let current = null;       // { id, level, onTimeUp }
  let ticker = null, endsAt = 0, lastTouch = Date.now(), closeTimer = null;

  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const shuffle = (a) => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const game = (id) => cfg && cfg.games.find((g) => g.id === id);
  const isOpen = () => !root.classList.contains('hidden');
  // Line icons (24 x 24 grid). The classic backup screen hides them.
  const svg = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
  const GAME_ICON = {
    riddles: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0 M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.7 M12 16.5h.01',
    memory: 'M4 8h9v12H4z M8 8V4.5h9.5v12H13',
    puzzle: 'M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M14.5 14.5h6v6h-6z',
    degree: 'M2.5 9.5 12 5l9.5 4.5L12 14 2.5 9.5z M6.5 11.7V16c1.6 1.3 3.4 2 5.5 2s3.9-.7 5.5-2v-4.3 M21.5 9.5v5',
    wordchain: 'M4 5h16v11H10l-4 3.5V16H4z M8 9h8 M8 12h5',
  };
  // Memory Match faces: the particle scene's topic drawings; emoji on the classic backup screen.
  const FACES = window.CynoParticles && CynoParticles.iconPaths
    ? [...new Set([...Object.values(CynoParticles.iconPaths), ...Object.values(GAME_ICON)])].map(svg)  // Set: the cap is in both lists
    : ['🤖', '💡', '🚀', '🎧', '💻', '📱', '🛰️', '🔋', '🎮', '⚙️', '🔭', '🧲'];

  async function loadConfig() {
    try { cfg = await (await fetch('/api/games')).json(); } catch (e) { cfg = null; }
    $('btnGames').classList.toggle('hidden', !(cfg && cfg.enabled));
    if (isOpen() && (!cfg || !cfg.enabled)) close();
    else if (isOpen() && !current) menu();
  }

  // ---------- shell ----------
  function shell(title, withTimer) {
    clearMini();  // a new game screen replaces one that was moved aside
    root.innerHTML = `
      <div class="g-panel">
        <div class="g-head">
          ${current ? '<button class="g-btn" id="gBack">All games</button>' : ''}
          <h1>${esc(title)}</h1>
          ${withTimer ? '<span class="g-time" id="gTime"></span>' : ''}
          <button class="g-btn" id="gClose">Close</button>
        </div>
        <div class="g-bar" ${withTimer ? '' : 'style="visibility:hidden"'}><i id="gBar"></i></div>
        <div class="g-body" id="gBody"></div>
      </div>`;
    root.classList.remove('hidden');
    $('gClose').onclick = close;
    if ($('gBack')) $('gBack').onclick = menu;
    return $('gBody');
  }

  function stopClock() { clearInterval(ticker); ticker = null; clearTimeout(closeTimer); closeTimer = null; }

  // The clock covers both limits: total play time, and (tap games and menus) time with no touch.
  let clockMode = { limited: false, voiceGame: false };
  function startClock(limited, voiceGame, leftMs) {
    stopClock();
    clockMode = { limited, voiceGame };
    const total = cfg.time_limit_secs;
    endsAt = Date.now() + (leftMs != null ? leftMs : total * 1000);
    lastTouch = Date.now();
    const tick = () => {
      const left = Math.max(0, Math.ceil((endsAt - Date.now()) / 1000));
      if (limited && $('gTime')) {
        $('gTime').textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
        $('gTime').classList.toggle('low', left <= 15);
        $('gBar').style.transform = `scaleX(${left / total})`;
      }
      if (limited && left <= 0) { const c = current; stopClock(); if (c && c.onTimeUp) c.onTimeUp(); else close(); return; }
      if (!voiceGame && Date.now() - lastTouch > cfg.idle_secs * 1000) close();
    };
    tick();
    ticker = setInterval(tick, 500);
  }

  function close() {
    stopClock();
    clearMini();
    current = null;
    root.classList.add('hidden');
    root.innerHTML = '';
  }

  function react(expression) {  // the face smiles on a win, if Cynobot isn't busy talking
    if (state.expression && state.expression !== 'IDLE') return;
    const post = (e) => fetch('/api/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expression: e }) }).catch(() => {});
    post(expression);
    setTimeout(() => { if (state.expression === expression) post('IDLE'); }, 2600);
  }

  // ---------- menu ----------
  function menu() {
    current = null;
    const body = shell('Games', false);
    const online = state.voice_mode !== 'OFFLINE';
    const tiles = cfg.games.filter((g) => !g.voice || online);
    body.innerHTML = `<div class="g-menu">${tiles.map((g, i) => `
      <button class="g-tile" data-game="${g.id}" style="animation-delay:${i * 0.05}s">
        ${GAME_ICON[g.id] ? svg(GAME_ICON[g.id]) : ''}<b>${esc(g.title)}</b><span>${esc(g.about)}</span><em>${g.voice ? 'Play by voice' : 'Tap to play'}</em>
      </button>`).join('')}</div>`;
    body.querySelectorAll('[data-game]').forEach((b) => (b.onclick = () => start(b.dataset.game)));
    startClock(false, false);
  }

  function start(id) {
    if (!game(id)) return menu();
    current = { id, level: '' };
    GAMES[id]();
  }

  function levelPick(title, question, levels, then) {
    const body = shell(title, false);
    body.innerHTML = `<div class="g-big">${esc(question)}</div>
      <div class="g-options ${levels.length < 4 ? 'one' : ''}">${levels.map((l) => `<button class="g-opt" data-level="${esc(l.id)}">${esc(l.label)}</button>`).join('')}</div>`;
    body.querySelectorAll('[data-level]').forEach((b) => (b.onclick = () => { current.level = b.dataset.level; then(b.dataset.level); }));
    startClock(false, false);
  }

  // ---------- result ----------
  const FORMAT = {
    riddles: (s) => `${s} / 5`,
    memory: (s) => `${s} moves`,
    puzzle: (s) => `${s} s`,
    wordchain: (s) => `${s} ${s === 1 ? 'word' : 'words'}`,
  };

  async function finish(score, headline, note) {
    const { id, level } = current;
    stopClock();
    let best = null, isBest = false;
    if (score != null) {
      try {
        const r = await (await fetch('/api/games/score', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ game: id, level, score }) })).json();
        best = r.best; isBest = r.is_best;
        if (cfg.best) cfg.best[`${id}:${level || 'any'}`] = best;
      } catch (e) {}
    }
    const body = shell(game(id) ? game(id).title : 'Games', false);
    body.innerHTML = `
      <div class="g-sub">${esc(headline)}</div>
      ${score != null ? `<div class="g-score">${esc(FORMAT[id](score))}</div>` : ''}
      ${isBest && score != null ? '<div class="g-badge">Best today</div>' : best != null ? `<div class="g-sub">Today's best: ${esc(FORMAT[id](best))}</div>` : ''}
      ${note ? `<div class="g-sub">${esc(note)}</div>` : ''}
      <div class="g-row"><button class="g-btn primary" id="gAgain">Play again</button><button class="g-btn" id="gMore">More games</button><button class="g-btn" id="gDone">Done</button></div>`;
    $('gAgain').onclick = () => start(id);
    $('gMore').onclick = menu;
    $('gDone').onclick = close;
    if (score != null) react('HAPPY');
    closeTimer = setTimeout(close, 20000);  // back to receptionist mode by itself
  }

  const GAMES = {
    // ---------- Brain Riddles ----------
    riddles() {
      levelPick('Brain Riddles', 'Choose your level', [{ id: 'easy', label: 'Easy' }, { id: 'medium', label: 'Tricky' }], (level) => {
        const pool = cfg.riddles.filter((r) => (r.level || 'easy') === level);
        const set = shuffle(pool.length >= 5 ? pool : cfg.riddles).slice(0, 5);
        let n = 0, right = 0;
        const body = shell('Brain Riddles', true);
        current.onTimeUp = () => finish(right, "Time's up!");
        const ask = () => {
          const r = set[n];
          const order = shuffle(r.options.map((o, i) => i));
          body.innerHTML = `<div class="g-step">Riddle ${n + 1} of ${set.length}</div><div class="g-big">${esc(r.q)}</div>
            <div class="g-options">${order.map((i) => `<button class="g-opt" data-i="${i}">${esc(r.options[i])}</button>`).join('')}</div><div class="g-sub" id="gWhy">&nbsp;</div>`;
          body.querySelectorAll('.g-opt').forEach((b) => (b.onclick = () => {
            if (body.dataset.locked) return;
            body.dataset.locked = '1';
            const ok = Number(b.dataset.i) === r.answer;
            if (ok) right++;
            b.classList.add(ok ? 'right' : 'wrong');
            body.querySelector(`[data-i="${r.answer}"]`).classList.add('right');
            $('gWhy').textContent = (ok ? 'Correct! ' : 'Not quite. ') + (r.why || '');
            setTimeout(() => {
              delete body.dataset.locked;
              if (current && current.id === 'riddles' && $('gBody') === body) (++n < set.length ? ask() : finish(right, right >= 4 ? 'Brilliant!' : right >= 2 ? 'Nice work!' : 'Good try!'));
            }, r.why ? 2600 : 1500);
          }));
        };
        ask();
        startClock(true, false);
      });
    },

    // ---------- Memory Match ----------
    memory() {
      const ICONS = FACES;
      levelPick('Memory Match', 'Choose your level', [{ id: 'easy', label: 'Easy: 6 pairs' }, { id: 'medium', label: 'Tricky: 8 pairs' }], (level) => {
        const pairs = level === 'easy' ? 6 : 8;
        const deck = shuffle(shuffle(ICONS).slice(0, pairs).flatMap((x) => [x, x]));
        const body = shell('Memory Match', true);
        body.innerHTML = `<div class="g-sub" id="gMoves">Find the pairs</div>
          <div class="g-cards" style="--cols:4;--rows:${deck.length / 4};grid-template-columns:repeat(4,1fr)">${deck.map((x, i) => `<div class="g-card" data-i="${i}"><div><i class="back">C</i><i class="front">${x}</i></div></div>`).join('')}</div>`;
        let up = [], moves = 0, found = 0, busy = false;
        current.onTimeUp = () => finish(null, "Time's up!", `You found ${found} of ${pairs} pairs.`);
        body.querySelectorAll('.g-card').forEach((c) => (c.onclick = () => {
          if (busy || c.classList.contains('up')) return;
          c.classList.add('up'); up.push(c);
          if (up.length < 2) return;
          moves++; $('gMoves').textContent = `${moves} ${moves === 1 ? 'move' : 'moves'}`;
          const [a, b] = up; up = [];
          if (deck[a.dataset.i] === deck[b.dataset.i]) {
            a.classList.add('done'); b.classList.add('done');
            if (++found === pairs) setTimeout(() => { if (current && current.id === 'memory') finish(moves, 'All pairs found!'); }, 700);
          } else {
            busy = true;
            setTimeout(() => { a.classList.remove('up'); b.classList.remove('up'); busy = false; }, 850);
          }
        }));
        startClock(true, false);
      });
    },

    // ---------- Picture Puzzle ----------
    puzzle() {
      if (!cfg.puzzle_images.length) { const b = shell('Picture Puzzle', false); b.innerHTML = '<div class="g-sub">No puzzle pictures yet. Add some in Cyno Control.</div>'; startClock(false, false); return; }
      levelPick('Picture Puzzle', 'How many pieces?', [{ id: 'easy', label: 'Easy: 4 pieces' }, { id: 'medium', label: 'Medium: 9 pieces' }, { id: 'hard', label: 'Hard: 16 pieces' }], (level) => {
        const n = { easy: 2, medium: 3, hard: 4 }[level];
        const src = cfg.puzzle_images[Math.floor(Math.random() * cfg.puzzle_images.length)];
        const body = shell('Picture Puzzle', true);
        body.innerHTML = '<div class="g-sub">Loading picture…</div>';
        const img = new Image();
        img.onerror = () => { body.innerHTML = '<div class="g-sub">That picture could not be loaded.</div>'; };
        img.onload = () => {
          if (!current || current.id !== 'puzzle' || $('gBody') !== body) return;
          body.innerHTML = `<div class="g-sub" id="gHint">Tap two pieces to swap them</div>
            <div class="g-puzzle"><div class="g-board" id="gBoard"></div><div class="g-ref"><img src="${esc(src)}" alt="" />Finished picture</div></div>`;
          const board = $('gBoard');
          const fit = () => {  // biggest board that keeps the picture's shape
            const maxH = Math.max(160, window.innerHeight - 250), maxW = Math.max(200, Math.min(window.innerWidth - (window.innerWidth > 760 ? 290 : 60), 1000));
            const ratio = img.naturalWidth / img.naturalHeight;
            const w = Math.min(maxW, maxH * ratio);
            board.style.width = `${w}px`; board.style.height = `${w / ratio}px`;
            board.style.gridTemplateColumns = `repeat(${n}, 1fr)`; board.style.gridTemplateRows = `repeat(${n}, 1fr)`;
          };
          fit(); window.addEventListener('resize', fit);
          let order = shuffle([...Array(n * n).keys()]);
          while (order.every((v, i) => v === i)) order = shuffle(order);
          let pick = null, began = Date.now(), solved = false;
          const draw = () => {
            board.innerHTML = order.map((piece, slot) => {
              const r = Math.floor(piece / n), c = piece % n;
              return `<div class="g-piece ${slot === pick ? 'pick' : ''}" data-slot="${slot}" style="background-image:url('${esc(src)}');background-size:${n * 100}% ${n * 100}%;background-position:${n > 1 ? (c / (n - 1)) * 100 : 0}% ${n > 1 ? (r / (n - 1)) * 100 : 0}%"></div>`;
            }).join('');
            board.querySelectorAll('.g-piece').forEach((p) => (p.onclick = () => {
              if (solved) return;
              const slot = Number(p.dataset.slot);
              if (pick === null) { pick = slot; return draw(); }
              if (pick !== slot) [order[pick], order[slot]] = [order[slot], order[pick]];
              pick = null; draw();
              if (order.every((v, i) => v === i)) {
                solved = true; board.classList.add('solved'); window.removeEventListener('resize', fit);
                const secs = Math.max(1, Math.round((Date.now() - began) / 1000));
                setTimeout(() => { if (current && current.id === 'puzzle') finish(secs, 'Picture complete!'); }, 1100);
              }
            }));
          };
          draw();
          current.onTimeUp = () => { window.removeEventListener('resize', fit); finish(null, "Time's up!", 'So close. Try again with fewer pieces?'); };
          startClock(true, false);
        };
        img.src = src;
      });
    },

    // ---------- Find Your Degree ----------
    degree() {
      const d = cfg.degree || {};
      if (!(d.levels && d.questions && d.programmes)) return menu();
      levelPick('Find Your Degree', 'Where are you in your studies?', d.levels, (level) => {
        const tally = {};
        let n = 0;
        const body = shell('Find Your Degree', true);
        current.onTimeUp = close;
        const result = () => {
          stopClock();
          const options = d.programmes[level] || [];
          const scored = options.map((p) => ({ p, s: Object.entries(p.tags || {}).reduce((t, [k, w]) => t + w * (tally[k] || 0), 0) }));
          scored.sort((a, b) => b.s - a.s);
          const top = scored[0] && scored[0].p, next = scored[1] && scored[1].p;
          if (!top) return menu();
          const out = shell('Find Your Degree', false);
          out.innerHTML = `<div class="g-step">Your IIT match</div>
            <div class="g-result-card"><div><h2>${esc(top.name)}</h2><p>${esc(top.why || '')}</p>
              ${next ? `<p style="margin-top:10px">Also worth a look: ${esc(next.name)}.</p>` : ''}
              <p style="margin-top:10px">Ask me about it, or talk to the admissions team to be sure.</p></div>
              ${cfg.admissions_link ? `<div class="qr"><img src="/api/qr?data=${encodeURIComponent(cfg.admissions_link)}" alt="QR code" /><span>${cfg.admissions_link.startsWith('mailto:') ? 'Scan to email admissions' : 'Scan with your phone'}</span></div>` : ''}</div>
            <div class="g-row"><button class="g-btn primary" id="gAgain">Try again</button><button class="g-btn" id="gMore">More games</button><button class="g-btn" id="gDone">Done</button></div>`;
          $('gAgain').onclick = () => start('degree'); $('gMore').onclick = menu; $('gDone').onclick = close;
          react('HAPPY');
          closeTimer = setTimeout(close, 45000);
        };
        const ask = () => {
          const q = d.questions[n];
          body.innerHTML = `<div class="g-step">Question ${n + 1} of ${d.questions.length}</div><div class="g-big">${esc(q.q)}</div>
            <div class="g-options">${q.options.map((o, i) => `<button class="g-opt" data-i="${i}">${esc(o.label)}</button>`).join('')}</div>`;
          body.querySelectorAll('.g-opt').forEach((b) => (b.onclick = () => {
            Object.entries(q.options[Number(b.dataset.i)].tags || {}).forEach(([k, w]) => (tally[k] = (tally[k] || 0) + w));
            ++n < d.questions.length ? ask() : result();
          }));
        };
        ask();
        startClock(true, false);
      });
    },

    // ---------- Word Chain (voice) ----------
    wordchain() {
      const body = shell('Word Chain', true);
      current.chain = []; current.botWord = ''; current.caption = state.last_spoken_text || '';
      current.onTimeUp = () => { const s = Math.max(0, current.chain.filter((w) => w.me).length); finish(s || null, "Time's up!", s ? 'Well played!' : 'Say "Word Chain" any time to play again.'); };
      if (state.voice_status !== 'LIVE' && window.CynoChest) window.CynoChest.startVoice();
      drawChain(body);
      startClock(true, true);
    },
  };

  // Word Chain follows the conversation: Cynobot answers "Robot. Your letter is T."
  const TURN = /^\W*([A-Za-z]{2,})\W+your letter is\W*([A-Za-z])\b/i;
  function drawChain(body) {
    const c = current;
    if (!c.botWord) {
      body.innerHTML = `<div class="g-sub">${state.voice_status === 'LIVE' ? 'Cynobot is listening' : 'Starting the conversation…'}</div>
        <div class="g-big">Say “Let's play Word Chain”</div>
        <div class="g-sub">Cynobot says a word. You say a word that starts with its last letter.</div>`;
      return;
    }
    const words = c.chain.filter((w) => w.me).length;
    body.innerHTML = `<div class="g-sub">Cynobot's word</div><div class="g-word">${esc(c.botWord)}</div>
      <div class="g-big">Your letter is <span class="g-letter">${esc(c.letter)}</span></div>
      <div class="g-chain">${c.chain.slice(-14).map((w) => `<span class="${w.me ? 'me' : ''}">${esc(w.word)}</span>`).join('')}</div>
      <div class="g-sub">${words ? `${words} ${words === 1 ? 'word' : 'words'} so far` : 'Your turn!'}</div>`;
  }
  function followChain() {
    const c = current, text = state.last_spoken_text || '';
    if (text === c.caption) { if (!c.botWord) drawChain($('gBody')); return; }
    c.caption = text;
    const m = TURN.exec(text);
    if (!m || m[1].toLowerCase() === c.botWord) return;
    if (c.botWord) {  // Cynobot accepted the visitor's word and answered with a new one
      const said = (state.user_text || '').replace(/[^A-Za-z\s'-]/g, ' ').trim().split(/\s+/).pop() || '';
      if (said) c.chain.push({ word: said.toLowerCase(), me: true });
    }
    c.botWord = m[1].toLowerCase(); c.letter = m[2];
    c.chain.push({ word: c.botWord, me: false });
    drawChain($('gBody'));
  }

  // ---------- a question mid-game ----------
  // When the visitor asks Cynobot something during a game, the game steps aside (its clock
  // paused) so the answer, card and QR code show properly. A button brings it back, and it
  // returns by itself a little while after Cynobot finishes, or when the visitor says
  // "back to the game".
  const AUTO_RESUME_SECS = 20;
  let mini = null;            // { left, title } while the game is moved aside
  let resumeAt = 0, miniTicker = null;
  let questionPending = false, requestText = null;  // what the visitor said when asking for a game
  const pill = document.createElement('button');
  pill.className = 'g-mini hidden';
  pill.id = 'gMini';
  document.body.appendChild(pill);
  pill.addEventListener('click', () => resume());

  function minimise() {
    if (!isOpen() || mini) return;
    if (!ticker) { close(); return; }  // the results screen: the game is over, so just make way
    mini = {
      left: clockMode.limited && ticker ? Math.max(1000, endsAt - Date.now()) : null,
      title: current && game(current.id) ? game(current.id).title : 'Games',
      mode: clockMode,
    };
    stopClock();
    root.classList.add('hidden');  // the game stays as it was underneath; only hidden
    resumeAt = 0;
    drawPill();
    pill.classList.remove('hidden');
    miniTicker = setInterval(miniTick, 500);
  }
  function resume() {
    if (!mini) return;
    const m = mini;
    clearMini();
    root.classList.remove('hidden');
    lastTouch = Date.now();
    startClock(m.mode.limited, m.mode.voiceGame, m.left);
  }
  function clearMini() {
    mini = null; resumeAt = 0;
    clearInterval(miniTicker); miniTicker = null;
    pill.classList.add('hidden');
  }
  function drawPill() {
    if (!mini) return;
    const left = mini.left != null ? Math.ceil(mini.left / 1000) : null;
    const time = left != null ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} left` : '';
    const back = resumeAt ? `Back in ${Math.max(0, Math.ceil((resumeAt - Date.now()) / 1000))} s` : '';
    pill.innerHTML = `${svg('M10 6 4 12l6 6 M4 12h16')}<span><b>Back to ${esc(mini.title)}</b><small>${[time, back].filter(Boolean).join(' · ') || 'Tap to continue'}</small></span>`;
  }
  function miniTick() {
    if (!mini) return;
    const busy = state.expression === 'THINKING' || state.expression === 'SPEAKING';
    if (busy) resumeAt = 0;                                   // still answering: wait
    else if (!resumeAt) resumeAt = Date.now() + AUTO_RESUME_SECS * 1000;  // answer done: start the countdown
    if (resumeAt && Date.now() >= resumeAt) { resume(); return; }
    drawPill();
  }
  // A question is pending when the visitor says something that is not a game command; the game
  // steps aside once Cynobot starts answering it.
  function watchQuestion(prev, s) {
    const said = s.user_text || '';
    if (said && said !== (prev.user_text || '')) {
      const wordChainMove = current && current.id === 'wordchain' && said.trim().split(/\s+/).length < 4;
      const sameTurnAsRequest = requestText != null && said.startsWith(requestText);  // "let's play riddles… please"
      questionPending = !wordChainMove && !sameTurnAsRequest;
      if (mini) resumeAt = 0;  // another question while the game is aside: keep it aside
    }
    if (s.expression === 'SPEAKING' && prev.expression !== 'SPEAKING' && questionPending) {
      questionPending = false;
      if (s.voice_status === 'LIVE') minimise();
    }
    if (mini && s.session_end === 'idle' && s.voice_status === 'OFFLINE') close();  // the visitor walked away
  }

  // ---------- wiring ----------
  window.CynoGames = {
    onState(s) {
      const prev = state;
      state = s;
      if (s.games_rev !== rev) { rev = s.games_rev; loadConfig(); }
      const req = s.game_request;
      if (req && req.ts > lastRequest) {
        lastRequest = req.ts;
        // Ignore a request left over from before this page loaded.
        if (cfg && cfg.enabled && req.ts > loadedAt - 3000) {
          requestText = s.user_text || ''; questionPending = false;
          if (mini && (req.id === 'resume' || req.id === 'menu' || (current && req.id === current.id))) resume();
          else if (req.id === 'resume') { if (!isOpen()) menu(); }
          else (req.id === 'menu' ? menu() : start(req.id));
        }
      }
      watchQuestion(prev, s);
      if (current && current.id === 'wordchain' && $('gBody') && current.chain) followChain();
    },
  };
  $('btnGames').addEventListener('click', () => { if (mini) resume(); else if (cfg && cfg.enabled) menu(); });
  ['pointerdown', 'keydown'].forEach((ev) => root.addEventListener(ev, () => { lastTouch = Date.now(); }));
  loadConfig();
})();
