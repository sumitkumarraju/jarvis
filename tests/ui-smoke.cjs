// Run with Playwright available on NODE_PATH: node tests/ui-smoke.cjs
// The bridge below is a test double, not a live model or microphone.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '../webui');
const server = http.createServer((req, res) => {
  const file = path.join(root, req.url === '/' ? 'index.html' : req.url.split('?')[0]);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (error, content) => {
    if (error) { res.writeHead(404).end(); return; }
    const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml' };
    res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
    res.end(content);
  });
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.addInitScript(() => {
      const info = {
        provider: 'ollama', model: 'qwen3.5:latest', voice: false, wake_mode: 'phrase_or_clap', busy: false, silence_timeout: 2,
        providers: [
          { id: 'ollama', label: 'Ollama', endpoint: 'http://localhost:11434', requires_key: false, key_configured: false },
          { id: 'omniroute', label: 'OmniRoute', endpoint: 'http://127.0.0.1:20128/v1', requires_key: true, key_configured: true },
        ],
      };
      window.bridgeCalls = [];
      window.pywebview = { api: {
        ready: async () => ({ ...info }),
        list_models: async provider => ({ provider, models: provider === 'ollama' ? ['qwen3.5:latest', 'llama3.1:latest'] : ['agy/claude-opus-4-6-thinking'], error: null }),
        select_model: async (provider, model) => {
          window.bridgeCalls.push(['select_model', provider, model]);
          if (model === 'bad-model') return { ok: false, error: 'This model is unavailable.', ...info };
          Object.assign(info, { provider, model });
          window.jarvisEvent('model_changed', { ...info });
          return { ok: true, error: null, provider, model };
        },
        send_message: async text => {
          window.bridgeCalls.push(['send_message', text]);
          window.jarvisEvent('turn_start', { text, voiced: false });
          setTimeout(() => {
            window.jarvisEvent('chunk', { text: 'Test reply for ' + text });
            window.jarvisEvent('turn_end');
          }, 100);
          return { ok: true, error: null };
        },
        set_wake_mode: async mode => {
          info.wake_mode = mode;
          window.jarvisEvent('wake_mode_changed', { wake_mode: mode });
          return { ok: true, error: null, wake_mode: mode };
        },
        toggle_voice: async () => {
          info.voice = !info.voice;
          window.jarvisEvent('voice_changed', { voice: info.voice });
          return info.voice;
        },
        reset: async () => { window.jarvisEvent('reset'); return { ok: true, error: null }; },
        interrupt: async () => { window.jarvisEvent('speech_stopped'); },
      } };
      window.addEventListener('DOMContentLoaded', () => window.dispatchEvent(new Event('pywebviewready')));
    });
    const url = `http://127.0.0.1:${server.address().port}`;
    await page.goto(url);
    await page.getByLabel('Model', { exact: true }).selectOption('llama3.1:latest');
    await page.getByRole('button', { name: 'Apply model', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('model').textContent === 'llama3.1:latest');
    assert.deepEqual(await page.evaluate(() => window.bridgeCalls[0]), ['select_model', 'ollama', 'llama3.1:latest']);
    await page.getByLabel('Message Jarvis').fill('Hello Jarvis');
    await page.getByRole('button', { name: 'Send message' }).click();
    await page.getByText('Test reply for Hello Jarvis', { exact: true }).waitFor();
    await page.getByLabel('Provider').selectOption('omniroute');
    await page.getByRole('button', { name: 'Apply model', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('model').textContent === 'agy/claude-opus-4-6-thinking');
    assert.equal(await page.getByText('Test reply for Hello Jarvis', { exact: true }).count(), 1, 'model switch preserves visible conversation');
    await page.getByRole('button', { name: 'Start listening', exact: true }).click();
    await page.getByRole('button', { name: 'Pause listening', exact: true }).waitFor();
    await page.getByLabel('Wake-up method').selectOption('clap');
    await page.getByText('Clap twice, then say one command. Microphone must be on.', { exact: true }).waitFor();
    await page.evaluate(() => window.jarvisEvent('mic_state', { state: 'waiting_wake', level: 0 }));
    await page.getByText('Waiting for two claps', { exact: true }).waitFor();
    await page.evaluate(() => window.jarvisEvent('mic_state', { state: 'awake', level: 0 }));
    await page.getByText('Awake. Say your command.', { exact: true }).waitFor();
    for (const [phase, label] of [['loading_model', 'Warming up speech recognition…'], ['hearing', 'Hearing you. Pause to send.'], ['transcribing', 'Turning speech into text…']]) {
      await page.evaluate(phase => window.jarvisEvent('mic_state', { state: phase, level: .02 }), phase);
      await page.getByText(label, { exact: true }).waitFor();
    }
    await page.evaluate(() => window.jarvisEvent('speech_transcript', { id: 'demo', text: 'Hey Jarvis, open Chrome', final: false, accepted: false }));
    await page.getByText('Hey Jarvis, open Chrome', { exact: true }).waitFor();
    await page.evaluate(() => window.jarvisEvent('speech_transcript', { id: 'demo', text: 'Hey Jarvis, open Chrome', final: true, accepted: true, reason: 'command' }));
    await page.getByText('Command recognized', { exact: true }).waitFor();
    await page.evaluate(() => window.jarvisEvent('processing_route', { message: 'Laya reactive command' }));
    await page.getByText('Laya reactive command', { exact: true }).waitFor();
    await page.evaluate(() => window.jarvisEvent('voice_changed', { voice: false }));
    await page.getByRole('button', { name: 'Start listening', exact: true }).waitFor();
    await page.getByLabel('Model', { exact: true }).selectOption('__custom__');
    await page.getByLabel('Custom model name').fill('bad-model');
    await page.getByRole('button', { name: 'Apply model', exact: true }).click();
    await page.getByText('This model is unavailable.', { exact: true }).waitFor();
    assert.equal(await page.locator('#model').textContent(), 'agy/claude-opus-4-6-thinking', 'failed switch retains active model');
    await page.evaluate(() => window.jarvisEvent('turn_start', { text: 'busy', voiced: false }));
    assert.equal(await page.getByRole('button', { name: 'Apply model', exact: true }).isDisabled(), true);
    assert.equal(await page.getByRole('button', { name: 'New conversation', exact: true }).isDisabled(), true);
    await page.evaluate(() => window.jarvisEvent('turn_end'));
    await page.getByRole('button', { name: 'New conversation', exact: true }).click();
    await page.getByRole('heading', { name: 'What can I do for you?' }).waitFor();
    await page.getByRole('button', { name: 'Control Spotify' }).click();
    assert.match(await page.getByLabel('Message Jarvis').inputValue(), /Spotify/);
    // A delayed discovery response must not overwrite the latest provider selection.
    await page.evaluate(() => {
      const original = window.pywebview.api.list_models;
      window.pywebview.api.list_models = async provider => {
        await new Promise(resolve => setTimeout(resolve, provider === 'ollama' ? 200 : 10));
        return original(provider);
      };
    });
    await page.getByLabel('Provider').selectOption('ollama');
    await page.getByLabel('Provider').selectOption('omniroute');
    await page.waitForTimeout(250);
    assert.equal(await page.getByLabel('Model', { exact: true }).inputValue(), 'agy/claude-opus-4-6-thinking');
    await page.screenshot({ path: '/tmp/jarvis-ui-desktop.png' });
    await page.getByRole('button', { name: 'Switch color theme' }).click();
    await page.waitForTimeout(220);
    const themeColors = await page.locator('.new-chat').evaluate(el => ({ color: getComputedStyle(el).color, background: getComputedStyle(el).backgroundColor }));
    assert.notEqual(themeColors.color, themeColors.background, 'theme preserves button contrast');
    await page.screenshot({ path: '/tmp/jarvis-ui-alternate-theme.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'mobile layout does not overflow');
    await page.screenshot({ path: '/tmp/jarvis-ui-mobile.png' });
    assert.deepEqual(errors, [], 'no frontend runtime errors');
    const preview = await browser.newPage();
    await preview.goto(url);
    await preview.getByText('Interface preview', { exact: true }).waitFor();
    assert.equal(await preview.getByRole('button', { name: 'Send message' }).isDisabled(), true, 'browser preview cannot fake model execution');
    console.log('PASS: model switching, chat streaming, voice state, switch failure, busy guards, reset, shortcuts, stale discovery, themes, responsive layout, preview mode.');
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });
