/* Mic, speaker and camera choice for Cynobot (set in Cyno Control > Controls > Devices).
   Devices are matched by name. "" means the browser's default device. Only this page is
   affected: system sound settings and other apps are untouched (same on macOS and Windows). */
(function () {
  let chosen = { mic: '', speaker: '', camera: '' };
  let lastScan = 0;
  let known = [];

  const KIND = { audioinput: 'mic', audiooutput: 'speaker', videoinput: 'camera' };
  const clean = (label) => String(label || '').replace(/^(Default|Communications)\s*-\s*/i, '').trim();

  async function refresh() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    try {
      known = await navigator.mediaDevices.enumerateDevices();
      const found = { mic: [], speaker: [], camera: [] };
      known.forEach((d) => { const n = clean(d.label); if (n && KIND[d.kind] && !found[KIND[d.kind]].includes(n)) found[KIND[d.kind]].push(n); });
      // Names only appear after the visitor (or the team) has allowed the mic/camera once.
      await fetch('/api/devices/seen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(found) });
    } catch (e) {}
  }

  function idFor(kind, name) {
    if (!name) return null;
    const d = known.find((x) => KIND[x.kind] === kind && clean(x.label) === name && x.deviceId !== 'default' && x.deviceId !== 'communications')
      || known.find((x) => KIND[x.kind] === kind && clean(x.label) === name);
    return d ? d.deviceId : null;
  }

  async function applySpeaker() {
    const audio = document.getElementById('botAudio');
    if (!audio || !audio.setSinkId) return;  // Safari can't choose a speaker; it uses the system one
    try { await audio.setSinkId(idFor('speaker', chosen.speaker) || ''); } catch (e) {}
  }

  // Full scan asked for from Cyno Control: allow mic and camera once so every name is visible.
  async function scan() {
    for (const c of [{ audio: true }, { video: true }]) {
      try { (await navigator.mediaDevices.getUserMedia(c)).getTracks().forEach((t) => t.stop()); } catch (e) {}
    }
    await refresh();
    applySpeaker();
  }

  window.CynoDevices = {
    /** Constraints for the chosen microphone (falls back to the default if it is unplugged). */
    audio(base) {
      const id = idFor('mic', chosen.mic);
      return id ? { ...base, deviceId: { exact: id } } : base;
    },
    /** Constraints for the chosen camera (used by Selfie with Cynobot). */
    video(base = {}) {
      const id = idFor('camera', chosen.camera);
      return id ? { ...base, deviceId: { exact: id } } : (Object.keys(base).length ? base : true);
    },
    refresh,
    onState(state) {
      if (state.devices && JSON.stringify(state.devices) !== JSON.stringify(chosen)) {
        chosen = { ...chosen, ...state.devices };
        refresh().then(applySpeaker);
      }
      if (state.device_scan && state.device_scan !== lastScan) {
        const first = lastScan === 0;
        lastScan = state.device_scan;
        if (!first || Date.now() - state.device_scan < 15000) scan();
      }
    },
  };

  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
    navigator.mediaDevices.addEventListener('devicechange', () => refresh().then(applySpeaker));
  }
  refresh().then(applySpeaker);
})();
