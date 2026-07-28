const els = {
  state: document.getElementById('state'),
  track: document.getElementById('track'),
  artist: document.getElementById('artist'),
  album: document.getElementById('album'),
  art: document.getElementById('albumArt'),
  fallback: document.getElementById('artFallback'),
  elapsed: document.getElementById('elapsed'),
  duration: document.getElementById('duration'),
  fill: document.getElementById('barFill'),
  seekBar: document.getElementById('seekBar'),
  previous: document.getElementById('previous'),
  playPause: document.getElementById('playPause'),
  next: document.getElementById('next'),
  repeat: document.getElementById('repeat'),
  playIcon: document.getElementById('playIcon'),
  pauseIcon: document.getElementById('pauseIcon'),
  notice: document.getElementById('notice'),
};

let current = { playing: false, duration_ms: 0, progress_ms: 0, repeat_state: 'off', received_at: Date.now() };
let noticeTimer;

function formatMs(ms) {
  const total = Math.max(0, Math.floor((ms || 0) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function showNotice(message) {
  els.notice.textContent = message || '';
  clearTimeout(noticeTimer);
  if (message) noticeTimer = setTimeout(() => { els.notice.textContent = ''; }, 9000);
}

function setArt(url) {
  if (url) {
    if (els.art.src !== url) els.art.src = url;
    document.body.style.setProperty('--cover-url', `url("${url}")`);
    els.art.hidden = false;
    els.fallback.hidden = true;
  } else {
    els.art.removeAttribute('src');
    document.body.style.removeProperty('--cover-url');
    els.art.hidden = true;
    els.fallback.hidden = false;
  }
}

function setPlayIcon(isPlaying) {
  els.playIcon.hidden = isPlaying;
  els.pauseIcon.hidden = !isPlaying;
}

function setRepeat(state) {
  els.repeat.classList.toggle('active', state && state !== 'off');
}

function renderEmpty(message, configured = true) {
  current = { playing: false, duration_ms: 0, progress_ms: 0, repeat_state: 'off', received_at: Date.now() };
  els.state.className = 'state idle';
  els.track.textContent = configured ? 'Nothing playing' : 'Spotify API not configured';
  els.artist.textContent = '';
  els.album.textContent = message || 'Start playback from your phone.';
  els.elapsed.textContent = '0:00';
  els.duration.textContent = '0:00';
  els.fill.style.width = '0%';
  setPlayIcon(false);
  setRepeat('off');
  setArt(null);
}

function displayProgress() {
  let progress = current.progress_ms || 0;
  const duration = current.duration_ms || 0;

  if (current.playing && duration) {
    progress += Date.now() - current.received_at;
  }

  progress = Math.max(0, duration ? Math.min(duration, progress) : progress);
  els.elapsed.textContent = formatMs(progress);
  els.duration.textContent = duration ? `-${formatMs(Math.max(0, duration - progress))}` : '0:00';
  const pct = duration ? Math.min(100, (progress / duration) * 100) : 0;
  els.fill.style.width = `${pct}%`;
}

function render(data) {
  if (!data.configured) {
    renderEmpty(data.message, false);
    return;
  }
  if (data.empty) {
    renderEmpty(data.message, true);
    return;
  }

  current = { ...data, received_at: Date.now() };
  els.state.className = data.playing ? 'state' : 'state paused';
  els.track.textContent = data.track;
  els.artist.textContent = data.artist;
  els.album.textContent = data.album;
  displayProgress();
  setPlayIcon(data.playing);
  setRepeat(data.repeat_state);
  setArt(data.album_art);
}

async function command(path, options = {}) {
  try {
    const response = await fetch(path, { cache: 'no-store', ...options });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      showNotice(data.message || 'Spotify control request failed.');
      return;
    }
    showNotice('');
    setTimeout(poll, 350);
  } catch (error) {
    showNotice('Local control service is not reachable.');
  }
}

async function poll() {
  try {
    const response = await fetch('/api/current', { cache: 'no-store' });
    const data = await response.json();
    render(data);
  } catch (error) {
    renderEmpty('Waiting for the local service.', true);
  }
}

function bindPress(el, handler) {
  el.addEventListener('pointerup', (event) => {
    event.preventDefault();
    handler(event);
  });
}

bindPress(els.previous, () => command('/api/previous', { method: 'POST' }));
bindPress(els.next, () => command('/api/next', { method: 'POST' }));
bindPress(els.playPause, () => {
  command(current.playing ? '/api/pause' : '/api/play', { method: 'PUT' });
});
bindPress(els.repeat, () => {
  const nextState = current.repeat_state && current.repeat_state !== 'off' ? 'off' : 'context';
  command(`/api/repeat?state=${nextState}`, { method: 'PUT' });
});
els.seekBar.addEventListener('pointerup', (event) => {
  event.preventDefault();
  if (!current.duration_ms) return;
  const rect = els.seekBar.getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  const position = Math.floor(current.duration_ms * ratio);
  command(`/api/seek?position_ms=${position}`, { method: 'PUT' });
});

poll();
setInterval(poll, 1500);
setInterval(displayProgress, 250);
