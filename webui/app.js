// === DOM refs ===
const chat = document.getElementById('chat');
const orb = document.getElementById('orb');
const stateLine = document.getElementById('state-line');
const meterBars = document.querySelectorAll('.meter span');
const composer = document.getElementById('composer');
const input = document.getElementById('prompt');
const btnVoice = document.getElementById('btn-voice');
const btnReset = document.getElementById('btn-reset');
const btnStop = document.getElementById('btn-stop');
const modelLabel = document.getElementById('model');

// === state ===
let currentJarvisBubble = null;

// === helpers ===
function addMessage(kind, text) {
  const wrap = document.createElement('div');
  wrap.className = `msg msg-${kind}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return bubble;
}

function setOrbState(state) {
  orb.dataset.state = state;
  stateLine.textContent = {
    idle:     'STANDBY',
    listen:   'LISTENING',
    thinking: 'PROCESSING',
    speak:    'SPEAKING',
  }[state] || state.toUpperCase();
}

function setMeter(level) {
  const peak = Math.min(1, level * 28);
  const lit = Math.round(peak * meterBars.length);
  meterBars.forEach((bar, i) => {
    if (i < lit) {
      const h = 4 + (peak * 28) * (1 - i / meterBars.length / 1.5);
      bar.style.height = `${Math.max(4, h)}px`;
      bar.style.opacity = 1;
    } else {
      bar.style.height = '4px';
      bar.style.opacity = 0.2;
    }
  });
}

// === event router (called from Python via window.jarvisEvent) ===
window.jarvisEvent = function(event, payload) {
  switch (event) {
    case 'mic_state':
      setOrbState(payload.state);
      setMeter(payload.level || 0);
      break;
    case 'user_voice':
      addMessage('user', payload.text);
      break;
    case 'turn_start':
      // user message added on send; on voice, already added above
      currentJarvisBubble = addMessage('jarvis', '');
      currentJarvisBubble.classList.add('cursor');
      break;
    case 'chunk':
      if (currentJarvisBubble) {
        currentJarvisBubble.textContent += payload.text;
        chat.scrollTop = chat.scrollHeight;
      }
      break;
    case 'tool': {
      const args = Object.entries(payload.args || {}).map(([k,v]) =>
        `${k}=${typeof v === 'string' ? `"${v}"` : v}`
      ).join(', ');
      addMessage('tool', `${payload.name}(${args})`);
      break;
    }
    case 'turn_end':
      if (currentJarvisBubble) currentJarvisBubble.classList.remove('cursor');
      currentJarvisBubble = null;
      break;
    case 'error':
      addMessage('system', `error: ${payload.message}`);
      break;
    case 'reset':
      chat.innerHTML = '';
      addMessage('system', 'Conversation cleared.');
      break;
    case 'speech_stopped':
      addMessage('system', 'Stopped.');
      break;
  }
};

// === inputs ===
composer.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMessage('user', text);
  await window.pywebview.api.send_message(text, false);
});

btnVoice.addEventListener('click', async () => {
  const on = await window.pywebview.api.toggle_voice();
  btnVoice.classList.toggle('active', on);
  setOrbState(on ? 'listen' : 'idle');
});

btnReset.addEventListener('click', () => window.pywebview.api.reset());
btnStop.addEventListener('click', () => window.pywebview.api.interrupt());

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') window.pywebview.api.interrupt();
  if (e.metaKey && e.key.toLowerCase() === 'v' && document.activeElement !== input) {
    btnVoice.click();
  }
});

// === boot ===
window.addEventListener('pywebviewready', async () => {
  const info = await window.pywebview.api.ready();
  modelLabel.textContent = info.model;
  setOrbState('idle');
});
