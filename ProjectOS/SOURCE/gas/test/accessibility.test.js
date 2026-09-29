const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {GAS_ROOT} = require('./helpers/load-gas');

const index = () => fs.readFileSync(path.join(GAS_ROOT, 'src/client/index.html'), 'utf8');
const styles = () => fs.readFileSync(path.join(GAS_ROOT, 'src/client/styles.html'), 'utf8');

function luminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi).map((value) => parseInt(value, 16) / 255)
    .map((value) => value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}
function contrast(first, second) {
  const [high, low] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
}

test('shell uses semantic landmarks, labels, live status, and keyboard-native controls', () => {
  const html = index();
  for (const element of ['header', 'nav', 'main', 'aside', 'footer']) assert.match(html, new RegExp(`<${element}\\b`));
  assert.match(html, /<label[^>]+for="project-search"/);
  assert.match(html, /id="project-search"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /<button\b/);
  assert.doesNotMatch(html, /onclick=/i);
});

test('Context OS tokens meet contrast, focus, target, and responsive requirements', () => {
  const css = styles();
  assert.ok(contrast('#f4f7fb', '#0b0f14') >= 4.5);
  assert.ok(contrast('#a8b3c2', '#131a23') >= 4.5);
  assert.ok(contrast('#07111f', '#4d8dff') >= 4.5);
  assert.match(css, /:focus-visible/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)/);
  assert.match(css, /prefers-reduced-motion/);
});

test('forms expose validation text and dialogs retain name role and value', () => {
  const html = index();
  assert.match(html, /aria-describedby="edit-help edit-error"/);
  assert.match(html, /id="edit-error"[^>]*role="alert"/);
  assert.match(html, /<dialog[^>]+aria-labelledby="edit-title"/);
  assert.match(html, /type="submit"/);
  assert.match(html, /type="button"/);
});

test('Looker experience has labelled regions responsive tables safe states and touch targets', () => {
  const html = index();
  const css = styles();
  assert.match(html, /id="looker-overview-title"/);
  assert.match(html, /aria-labelledby="looker-overview-title"/);
  assert.match(css, /\.looker-table-wrap[^}]*overflow-x:\s*auto/s);
  assert.match(css, /\.looker-action[^}]*min-height:\s*44px/s);
  assert.match(css, /\.looker-state/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)/);
});
