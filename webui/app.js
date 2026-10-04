'use strict';

const $ = id => document.getElementById(id);
const chat = $('chat');
const input = $('prompt');
const providerSelect = $('provider-select');
const modelSelect = $('model-select');
const modelStatus = $('model-status');
const messageStatus = $('message-status');
const meterBars = document.querySelectorAll('.meter span');
const state = { connected: false, busy: false, voice: false, loading: false, applying: false, voicePending: false, voicePhase: 'starting', wakeMode: 'phrase_or_clap', wakePending: false, provider: '', model: '', providers: [], discovery: 0 };
let currentJarvisBubble = null;
let booting = false;
let speechActive = false;

function status(element, text, error = false) {
  element.textContent = text || '';
  element.dataset.error = String(error);
}

function selectedModel() {
  return modelSelect.value === '__custom__' ? $('custom-model').value.trim() : modelSelect.value;
}

function syncControls() {
  const locked = !state.connected || state.busy || state.applying;
  providerSelect.disabled = locked;
  modelSelect.disabled = locked || state.loading;
  $('custom-model').disabled = locked || state.loading;
  $('btn-refresh').disabled = locked || state.loading;
  const provider = state.providers.find(item => item.id === providerSelect.value);
  const missingKey = provider && provider.requires_key && !provider.key_configured;
  $('btn-apply').disabled = locked || state.loading || !selectedModel() || missingKey;
  $('btn-reset').disabled = locked;
  $('send').disabled = locked || !input.value.trim();
  input.disabled = !state.connected || state.applying;
  $('btn-voice').disabled = !state.connected || state.voicePending || state.applying;
  $('wake-mode').disabled = locked || state.wakePending || state.voicePending;
  $('btn-stop').disabled = !state.connected || !speechActive;
  document.querySelectorAll('.suggestion').forEach(button => { button.disabled = locked; });
  chat.setAttribute('aria-busy', String(state.busy));
  $('btn-apply').firstChild.textContent = state.applying ? 'Switching… ' : 'Apply model ';
  $('composer-hint').textContent = state.busy ? 'Jarvis is working. You can draft your next message.' : state.voice ? 'Microphone on. Speak or type a message.' : 'Microphone paused. Type a message or start listening.';
}

function scrollChat() {
  const container = $('chat-scroll');
  container.scrollTop = container.scrollHeight;
}

function addMessage(kind, text) {
  $('welcome').hidden = true;
  const wrap = document.createElement('div');
  wrap.className = `msg msg-${kind}`;
  if (kind === 'user' || kind === 'jarvis') {
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.setAttribute('aria-hidden', 'true');
    avatar.textContent = kind === 'jarvis' ? 'J' : 'You';
    wrap.appendChild(avatar);
  }
  const content = document.createElement('div');
  content.className = 'message-content';
  if (kind === 'user' || kind === 'jarvis') {
    const author = document.createElement('div');
    author.className = 'message-author';
    author.textContent = kind === 'jarvis' ? 'Jarvis' : 'You';
    content.appendChild(author);
  }
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  content.appendChild(bubble);
  wrap.appendChild(content);
  chat.appendChild(wrap);
  scrollChat();
  return bubble;
}

function setVoice(on) {
  state.voice = Boolean(on);
  $('btn-voice').textContent = state.voice ? 'Pause listening' : 'Start listening';
  $('btn-voice').classList.toggle('active', state.voice);
  $('btn-voice').setAttribute('aria-pressed', String(state.voice));
  $('voice-badge').textContent = state.voice ? 'On' : 'Paused';
  $('voice-badge').classList.toggle('active', state.voice);
  if (!state.voice) setMeter(0);
  if (!state.busy) setActivity(state.voice ? state.voicePhase : 'idle');
  syncControls();
}

function setActivity(activity) {
  $('orb').dataset.state = activity;
  const wakeLabel = { phrase: 'Waiting for “Hey Jarvis”', clap: 'Waiting for two claps', phrase_or_clap: 'Waiting for a wake phrase or clap', always: 'Listening for your voice' }[state.wakeMode];
  $('state-line').textContent = { waiting_wake: wakeLabel, awake: 'Awake. Say your command.', idle: 'Microphone paused', starting: 'Opening your microphone…', loading_model: 'Warming up speech recognition…', listen: 'Listening for your voice', hearing: 'Hearing you. Pause to send.', transcribing: 'Turning speech into text…', thinking: 'Processing your request', speak: 'Speaking a response' }[activity] || activity;
  speechActive = activity === 'speak';
  syncControls();
}

function setMeter(level) {
  const peak = Math.max(0, Math.min(1, Number(level) * 28 || 0));
  meterBars.forEach((bar, i) => {
    bar.style.height = `${4 + peak * 22 * (1 - Math.abs(i - 7.5) / 10)}px`;
    bar.style.opacity = peak > 0 ? .4 + peak * .6 : .25;
    bar.style.setProperty('--i', i);
  });
}

function showProviderDetails() {
  const provider = state.providers.find(item => item.id === providerSelect.value);
  $('endpoint').textContent = provider?.endpoint || 'Endpoint configured in your environment.';
  $('privacy-note').textContent = providerSelect.value === 'ollama'
    ? 'Ollama runs locally by default. A remote endpoint sends data off this Mac.'
    : 'Your gateway may send requests to an upstream provider. API keys stay in Python.';
  $('model-note').textContent = provider?.requires_key && !provider.key_configured
    ? 'Set OPENAI_API_KEY before launching to use this provider.'
    : 'Models with tool calling work best.';
  syncControls();
}

function customField() {
  $('custom-model-field').hidden = modelSelect.value !== '__custom__';
  syncControls();
}

async function discoverModels() {
  const provider = providerSelect.value;
  const request = ++state.discovery;
  state.loading = true;
  status(modelStatus, 'Looking for available models…');
  showProviderDetails();
  try {
    const result = await window.pywebview.api.list_models(provider);
    if (request !== state.discovery) return;
    const models = [...new Set((result.models || []).filter(model => typeof model === 'string' && model))];
    if (provider === state.provider && state.model && !models.includes(state.model)) models.unshift(state.model);
    modelSelect.replaceChildren();
    models.forEach(model => modelSelect.add(new Option(model, model)));
    modelSelect.add(new Option('Enter a custom model…', '__custom__'));
    modelSelect.value = provider === state.provider && models.includes(state.model) ? state.model : models[0] || '__custom__';
    $('custom-model').value = '';
    status(modelStatus, result.error || (models.length ? `${models.length} model${models.length === 1 ? '' : 's'} available. Select one and apply.` : 'No models found. Enter an exact model ID or refresh after starting your provider.'), Boolean(result.error));
  } catch (error) {
    if (request !== state.discovery) return;
    modelSelect.replaceChildren(new Option('Enter a custom model…', '__custom__'));
    status(modelStatus, `Could not discover models: ${error.message || error}`, true);
  } finally {
    if (request === state.discovery) {
      state.loading = false;
      customField();
    }
  }
}

function activeModel(info) {
  state.provider = info.provider;
  state.model = info.model;
  if (info.providers) state.providers = info.providers;
  $('model').textContent = info.model;
  $('provider-label').textContent = state.providers.find(item => item.id === info.provider)?.label || info.provider;
}

window.jarvisEvent = (event, payload = {}) => {
  switch (event) {
    case 'mic_state':
      if (['starting', 'loading_model', 'listen', 'hearing', 'transcribing', 'idle', 'waiting_wake', 'awake'].includes(payload.state)) state.voicePhase = payload.state;
      setActivity(payload.state);
      setMeter(payload.level);
      break;
    case 'voice_changed':
      setVoice(payload.voice);
      break;
    case 'speech_transcript':
      showLyrics(payload);
      break;
    case 'wake_mode_changed':
      updateWakeMode(payload.wake_mode);
      if (state.voice && !state.busy) {
        state.voicePhase = state.wakeMode === 'always' ? 'listen' : 'waiting_wake';
        setActivity(state.voicePhase);
      }
      break;
    case 'processing_route':
      status(messageStatus, payload.message);
      break;
    case 'model_changed':
      activeModel(payload);
      status(modelStatus, 'Model switched. Your conversation is kept.');
      break;
    case 'user_voice':
      addMessage('user', payload.text);
      break;
    case 'turn_start':
      state.busy = true;
      status(messageStatus, '');
      currentJarvisBubble = addMessage('jarvis', '');
      currentJarvisBubble.classList.add('cursor');
      setActivity('thinking');
      break;
    case 'chunk':
      if (currentJarvisBubble) {
        currentJarvisBubble.textContent += payload.text;
        scrollChat();
      }
      break;
    case 'tool':
      addMessage('tool', `Using ${payload.name} · ${JSON.stringify(payload.args || {})}`);
      break;
    case 'turn_end':
      if (currentJarvisBubble) {
        currentJarvisBubble.classList.remove('cursor');
        if (!currentJarvisBubble.textContent) currentJarvisBubble.textContent = 'No response received. Check your model connection and try again.';
      }
      currentJarvisBubble = null;
      state.busy = false;
      setActivity(state.voice ? state.voicePhase : 'idle');
      syncControls();
      break;
    case 'error':
      status(messageStatus, payload.message, true);
      addMessage('error', payload.message);
      break;
    case 'reset':
      chat.replaceChildren();
      currentJarvisBubble = null;
      $('welcome').hidden = false;
      status(messageStatus, 'New conversation started.');
      break;
    case 'speech_stopped':
      speechActive = false;
      status(messageStatus, 'Speech stopped. Any in-progress request will still finish.');
      syncControls();
      break;
  }
};

$('model-form').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('btn-apply').disabled) return;
  state.applying = true;
  const provider = providerSelect.value;
  const model = selectedModel();
  syncControls();
  status(modelStatus, 'Switching model…');
  try {
    const result = await window.pywebview.api.select_model(provider, model);
    if (!result.ok) { status(modelStatus, result.error || 'Could not switch models.', true); return; }
    activeModel(result);
    status(modelStatus, 'Model switched. Your conversation is kept.');
  } catch (error) {
    status(modelStatus, `Could not switch models: ${error.message || error}`, true);
  } finally {
    state.applying = false;
    syncControls();
  }
});
providerSelect.addEventListener('change', discoverModels);
modelSelect.addEventListener('change', customField);
$('custom-model').addEventListener('input', syncControls);
$('btn-refresh').addEventListener('click', discoverModels);

function resizeInput() {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  syncControls();
}
input.addEventListener('input', resizeInput);
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('composer').requestSubmit();
  }
});
$('composer').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('send').disabled) return;
  const text = input.value.trim();
  const userBubble = addMessage('user', text);
  input.value = '';
  state.busy = true;
  resizeInput();
  try {
    const result = await window.pywebview.api.send_message(text, false);
    if (result && !result.ok) throw new Error(result.error || 'Message was not accepted.');
  } catch (error) {
    userBubble.closest('.msg').remove();
    $('welcome').hidden = Boolean(chat.childElementCount);
    input.value = text;
    state.busy = false;
    status(messageStatus, error.message || String(error), true);
    resizeInput();
  }
});

$('btn-voice').addEventListener('click', async () => {
  if ($('btn-voice').disabled) return;
  state.voicePending = true;
  syncControls();
  try {
    const on = await window.pywebview.api.toggle_voice();
    setVoice(on);
  } catch (error) {
    status(messageStatus, `Could not start microphone: ${error.message || error}`, true);
    setVoice(false);
  } finally {
    state.voicePending = false;
    syncControls();
  }
});
function showLyrics(payload) {
  const panel = $('speech-lyrics');
  panel.hidden = false;
  panel.dataset.final = String(Boolean(payload.final));
  $('lyrics-label').textContent = payload.final ? (payload.accepted ? 'Command recognized' : 'Heard you') : 'Listening';
  $('lyrics-state').textContent = payload.final ? (payload.accepted ? 'Sending' : 'Waiting for wake') : 'Draft';
  $('lyrics-text').replaceChildren();
  const words = (payload.text || '').split(/(\s+)/);
  words.forEach((word, index) => {
    const span = document.createElement('span');
    span.textContent = word;
    if (word.trim()) {
      span.className = 'lyric-word';
      span.style.setProperty('--word-index', index);
    }
    $('lyrics-text').appendChild(span);
  });
  $('lyrics-note').textContent = payload.final
    ? payload.accepted ? 'Jarvis is processing this command.' : 'No action was started. Say “Hey Jarvis” or change the wake-up method.'
    : 'Live speech draft. Drafts never execute commands.';
}

function updateWakeMode(mode) {
  state.wakeMode = mode;
  $('wake-mode').value = mode;
  $('voice-hint').textContent = {
    always: 'Every utterance is a command while the microphone is on. Use the toggle to pause.',
    phrase: 'Say “Hey Jarvis” or “Wake up Jarvis”, then give one command.',
    clap: 'Clap twice, then say one command. Microphone must be on.',
    phrase_or_clap: 'Say “Hey Jarvis” or “Wake up Jarvis”, or clap twice. Then give one command.',
  }[mode] || 'Choose a wake-up method.';
}
$('wake-mode').addEventListener('change', async () => {
  const previous = state.wakeMode;
  state.wakePending = true;
  syncControls();
  try {
    const result = await window.pywebview.api.set_wake_mode($('wake-mode').value);
    if (!result.ok) throw new Error(result.error || 'Could not change wake-up method.');
    updateWakeMode(result.wake_mode);
  } catch (error) {
    updateWakeMode(previous);
    status(messageStatus, error.message || String(error), true);
  } finally {
    state.wakePending = false;
    syncControls();
  }
});
$('btn-reset').addEventListener('click', async () => {
  if ($('btn-reset').disabled) return;
  try {
    const result = await window.pywebview.api.reset();
    if (result && !result.ok) status(messageStatus, result.error, true);
  } catch (error) { status(messageStatus, error.message || String(error), true); }
});
$('btn-stop').addEventListener('click', async () => {
  if ($('btn-stop').disabled) return;
  try { await window.pywebview.api.interrupt(); }
  catch (error) { status(messageStatus, error.message || String(error), true); }
});
document.querySelectorAll('.suggestion').forEach(button => {
  button.addEventListener('click', () => {
    input.value = button.dataset.prompt;
    resizeInput();
    input.focus();
  });
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') $('btn-stop').click();
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
    event.preventDefault();
    $('btn-reset').click();
  }
  if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === 'v') {
    event.preventDefault();
    $('btn-voice').click();
  }
});

try {
  const savedTheme = localStorage.getItem('jarvis-theme');
  if (['light', 'dark'].includes(savedTheme)) document.documentElement.dataset.theme = savedTheme;
} catch (_) { /* Storage may be disabled in a webview. */ }
$('btn-theme').addEventListener('click', () => {
  const isDark = document.documentElement.dataset.theme === 'dark' || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
  const theme = isDark ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('jarvis-theme', theme); } catch (_) { /* Optional preference only. */ }
});

async function boot() {
  if (booting || state.connected || !window.pywebview?.api) return;
  booting = true;
  try {
    const info = await window.pywebview.api.ready();
    state.connected = true;
    state.busy = Boolean(info.busy);
    activeModel(info);
    if (info.speech_transcript) showLyrics(info.speech_transcript);
    providerSelect.replaceChildren();
    state.providers.forEach(provider => providerSelect.add(new Option(provider.label, provider.id)));
    providerSelect.value = info.provider;
    $('preview-banner').hidden = true;
    $('connection-label').textContent = 'Desktop connected';
    $('connection-dot').classList.add('connected');
    updateWakeMode(info.wake_mode || 'always');
    state.voicePhase = info.voice_phase || (info.voice ? 'listen' : 'idle');
    setVoice(info.voice);
    if (state.busy) setActivity('thinking');
    syncControls();
    await discoverModels();
  } catch (error) {
    status(messageStatus, `Could not connect to Jarvis: ${error.message || error}. Relaunch the desktop app.`, true);
  } finally { booting = false; }
}
window.addEventListener('pywebviewready', boot);
boot();
setTimeout(() => {
  if (!state.connected && !window.pywebview?.api) {
    $('preview-banner').hidden = false;
    $('connection-label').textContent = 'Preview only';
    $('composer-hint').textContent = 'Launch the desktop app to send messages.';
  }
}, 800);
