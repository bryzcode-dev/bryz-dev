import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
function option(name, fallback) {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
}
const fixturePath = path.resolve(option('--fixture', path.join(root, 'test/fixtures/ui-roles.json')));
const port = Number(option('--port', '4173'));
const fixtures = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const index = fs.readFileSync(path.join(root, 'src/client/index.html'), 'utf8');
const styles = fs.readFileSync(path.join(root, 'src/client/styles.html'), 'utf8');
const app = fs.readFileSync(path.join(root, 'src/client/app.html'), 'utf8');

function render(requestUrl) {
  const url = new URL(requestUrl, `http://127.0.0.1:${port}`);
  const role = String(url.searchParams.get('role') || 'owner').toLowerCase();
  const fixture = fixtures[Object.hasOwn(fixtures, role) ? role : 'owner'];
  const injected = `<script>window.__PROJECTOS_FIXTURE__=${JSON.stringify(fixture).replace(/</g, '\\u003c')};</script>\n${app}`;
  return index.replace("<?!= include('styles'); ?>", styles).replace("<?!= include('app'); ?>", injected);
}

const server = http.createServer((request, response) => {
  const url = new URL(request.url, `http://127.0.0.1:${port}`);
  if (url.pathname !== '/' && url.pathname !== '/index.html') {
    response.writeHead(404, {'Content-Type': 'text/plain; charset=utf-8'}); response.end('Not found'); return;
  }
  response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"});
  response.end(render(request.url));
});
server.listen(port, '127.0.0.1', () => console.log(`ProjectOS preview: http://127.0.0.1:${port}/?role=owner`));
