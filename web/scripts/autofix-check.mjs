// Temporary gate: run every .svelte file through the Svelte MCP svelte-autofixer.
// Spawned as `npx -y @sveltejs/mcp`, spoken to over newline-delimited JSON-RPC (stdio).
import { spawn } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative } from 'node:path';

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(WEB_ROOT, 'src');

function walk(dir) {
	const out = [];
	for (const name of readdirSync(dir)) {
		const p = join(dir, name);
		if (statSync(p).isDirectory()) out.push(...walk(p));
		else if (name.endsWith('.svelte')) out.push(p);
	}
	return out;
}

const files = walk(SRC);
console.log(`autofix-check: ${files.length} svelte files`);

const child = spawn('npx', ['-y', '@sveltejs/mcp'], {
	cwd: WEB_ROOT,
	shell: true,
	stdio: ['pipe', 'pipe', 'pipe']
});
child.stderr.on('data', (d) => process.stderr.write(d));

let buf = '';
const pending = new Map();
let nextId = 1;

function send(msg) {
	child.stdin.write(JSON.stringify(msg) + '\n');
}

function request(method, params) {
	const id = nextId++;
	const p = new Promise((resolve, reject) => {
		const t = setTimeout(() => reject(new Error(`timeout on ${method} #${id}`)), 120_000);
		pending.set(id, (res) => {
			clearTimeout(t);
			resolve(res);
		});
	});
	send({ jsonrpc: '2.0', id, method, params });
	return p;
}

child.stdout.on('data', (chunk) => {
	buf += chunk.toString();
	let idx;
	while ((idx = buf.indexOf('\n')) !== -1) {
		const line = buf.slice(0, idx).trim();
		buf = buf.slice(idx + 1);
		if (!line) continue;
		let msg;
		try {
			msg = JSON.parse(line);
		} catch {
			continue;
		}
		if (msg.id !== undefined && pending.has(msg.id)) {
			const cb = pending.get(msg.id);
			pending.delete(msg.id);
			cb(msg);
		}
	}
});

let failures = 0;

const initRes = await request('initialize', {
	protocolVersion: '2024-11-05',
	capabilities: {},
	clientInfo: { name: 'autofix-check', version: '1.0.0' }
});
if (initRes.error) {
	console.error('initialize failed:', JSON.stringify(initRes.error));
	process.exit(2);
}
console.log('MCP server ready:', initRes.result?.serverInfo?.name ?? '?');
send({ jsonrpc: '2.0', method: 'notifications/initialized' });

for (const file of files) {
	const rel = relative(WEB_ROOT, file);
	const code = readFileSync(file, 'utf8');
	const res = await request('tools/call', {
		name: 'svelte-autofixer',
		arguments: { code, filename: rel, desired_svelte_version: 5 }
	});
	if (res.error) {
		failures++;
		console.error(`✗ ${rel}: tool error ${JSON.stringify(res.error)}`);
		continue;
	}
	const text = res.result?.content?.map((c) => c.text ?? '').join('') ?? '';
	let report;
	try {
		report = JSON.parse(text);
	} catch {
		failures++;
		console.error(`✗ ${rel}: unparseable report ${text.slice(0, 200)}`);
		continue;
	}
	const diags = report.diagnostics ?? [];
	if (diags.length === 0) {
		console.log(`✓ ${rel}`);
	} else {
		failures++;
		console.error(`✗ ${rel}: ${diags.length} diagnostic(s)`);
		for (const d of diags) console.error(`   ${d.severity ?? ''} ${d.code ?? ''} ${d.message ?? ''}`);
	}
}

child.kill();
console.log(failures === 0 ? 'autofix-check: ALL GREEN' : `autofix-check: ${failures} file(s) failed`);
process.exit(failures === 0 ? 0 : 1);
