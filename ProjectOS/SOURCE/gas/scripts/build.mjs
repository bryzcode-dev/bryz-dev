import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argumentsList = process.argv.slice(2);
const outIndex = argumentsList.indexOf('--out');
const output = outIndex >= 0 ? path.resolve(argumentsList[outIndex + 1]) : path.join(root, 'dist');
const order = JSON.parse(fs.readFileSync(path.join(root, 'source-order.json'), 'utf8'));
if (!Array.isArray(order.server) || !order.server.length) throw new Error('source-order.json must name server sources');
const parts = order.server.map((relative) => {
  if (!relative.startsWith('src/server/') || !relative.endsWith('.js')) throw new Error(`invalid server source: ${relative}`);
  const content = fs.readFileSync(path.join(root, relative), 'utf8').replace(/\s+$/u, '');
  return `// source: ${relative}\n${content}\n`;
});
fs.mkdirSync(output, {recursive: true});
fs.writeFileSync(path.join(output, 'Code.gs'), parts.join('\n'), 'utf8');
for (const relative of order.client || []) {
  if (!relative.startsWith('src/client/') || !relative.endsWith('.html')) throw new Error(`invalid client source: ${relative}`);
  fs.copyFileSync(path.join(root, relative), path.join(output, path.basename(relative)));
}
