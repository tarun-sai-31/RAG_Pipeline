// `npm start`: runs `ng serve` with a Node version Angular accepts.
// If this terminal's Node is too old (e.g. a VS Code terminal opened before Node was updated),
// the newest suitable Node installed with nvm is used instead, so no `nvm use` is needed.
import { spawn } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

// Angular CLI 22: ^22.22.3 || ^24.15.0 || >=26.0.0
const supported = ([major, minor, patch]) =>
  (major === 22 && (minor > 22 || (minor === 22 && patch >= 3))) || (major === 24 && minor >= 15) || major >= 26;
const parse = (v) => v.replace(/^v/, '').split('.').map(Number);
const compare = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

function pickNode() {
  if (supported(parse(process.version))) return process.execPath;
  const dir = join(process.env.NVM_DIR || join(homedir(), '.nvm'), 'versions', 'node');
  const candidates = existsSync(dir)
    ? readdirSync(dir)
        .filter((v) => supported(parse(v)) && existsSync(join(dir, v, 'bin', 'node')))
        .sort((a, b) => compare(parse(b), parse(a)))
    : [];
  if (!candidates.length) {
    console.error(
      `Node ${process.version} is too old for Angular (needs 24.15+). Install a newer one: nvm install 24`,
    );
    process.exit(1);
  }
  console.log(`Node ${process.version} is too old for Angular; using ${candidates[0]} from nvm.`);
  return join(dir, candidates[0], 'bin', 'node');
}

const ng = join(import.meta.dirname, '..', 'node_modules', '@angular', 'cli', 'bin', 'ng.js');
const child = spawn(pickNode(), [ng, 'serve', ...process.argv.slice(2)], { stdio: 'inherit' });
child.on('exit', (code, signal) => process.exit(signal ? 1 : (code ?? 0)));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => child.kill(sig));
