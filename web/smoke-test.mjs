// Smoke test: runs the built app (adapter-node, `node build`) against the mock
// backend and asserts real HTTP behavior. The UI is fully client-rendered over
// SSE, so HTML checks verify the shell + SSR state paint; data assertions run
// against the API itself, and the approve loop is verified end-to-end through
// the store's own code path (client.ts) — approve → PENDING → IN_TRANSIT → ARRIVED.
//
// Usage:  node web/smoke-test.mjs
// Prereq: none (script starts mock + built app itself).

import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { access } from 'node:fs/promises';

const MOCK_PORT = 8090;
const WEB_PORT = 4173;
const API = `http://localhost:${MOCK_PORT}`;
const WEB = `http://localhost:${WEB_PORT}`;

let failures = 0;
function check(name, cond, extra = '') {
	if (cond) {
		console.log(`  ok  ${name}`);
	} else {
		failures++;
		console.error(`FAIL  ${name}${extra ? ` — ${extra}` : ''}`);
	}
}

async function j(url, opts) {
	const res = await fetch(url, opts);
	return { status: res.status, body: await res.json().catch(() => null) };
}

async function waitFor(url, matches, tries = 40, delayMs = 500) {
	for (let i = 0; i < tries; i++) {
		try {
			const res = await fetch(url);
			const text = await res.text();
			if (matches.every((m) => text.includes(m))) return true;
		} catch { /* not up yet */ }
		await sleep(delayMs);
	}
	return false;
}

async function main() {
	// 0. build check
	await access('./build/index.js').catch(() => {
		console.error('web/build missing — run `npm run build` in web/ first');
		process.exit(1);
	});

	console.log('starting mock backend…');
	const mock = spawn(process.execPath, ['mock-backend.mjs'], {
		env: { ...process.env, MOCK_PORT: String(MOCK_PORT) },
		stdio: 'inherit'
	});
	await waitFor(`${API}/api/state`, ['"is_stale"']);

	console.log('starting built app (node build)…');
	const web = spawn(process.execPath, ['build'], {
		env: {
			...process.env,
			PORT: String(WEB_PORT),
			HOST: '127.0.0.1',
			PUBLIC_API_BASE: API, // adapter-node runtime env overrides baked value
			PROTOCOL_HEADER: 'x-forwarded-proto'
		},
		stdio: 'inherit'
	});
	await waitFor(WEB, ['FUELINTEL']);

	try {
		// 1. Shell + SSR paint of live data on every screen
		console.log('screen checks:');
		const overview = await (await fetch(`${WEB}/`)).text();
		check('Overview paints depot from SSR state', overview.includes('Gazipur Depot'));
		check('Overview paints inventory numbers', overview.includes('60,000 L'));
		check('Stale banner absent initially', !overview.includes('Stale data'));

		const alertsHtml = await (await fetch(`${WEB}/alerts`)).text();
		check('Alerts paints CRITICAL severity', alertsHtml.includes('CRITICAL'));
		check('Alerts paints GenAI explanation', alertsHtml.includes('Mirpur is burning'));

		const recsHtml = await (await fetch(`${WEB}/recommendations`)).text();
		check('Recommendations paints policy tag', recsHtml.includes('OPTIMIZER'));
		check('Recommendations paints risk delta', recsHtml.includes('72'));
		check('Recommendations paints review badge (low confidence 0.42)', recsHtml.includes('Human review requested'));

		const healthHtml = await (await fetch(`${WEB}/health`)).text();
		check('Health paints component table', healthHtml.includes('forecaster'));
		check('Health badge in top bar shows Healthy', healthHtml.includes('>Healthy<'));

		// 2. Mock controls work: tick mutates state (the UI's SSE loop picks it up)
		console.log('mock control checks:');
		const before = await j(`${API}/api/state`);
		await j(`${API}/__mock__/tick`, { method: 'POST' });
		const after = await j(`${API}/api/state`);
		check('mock tick advances tick', after.body.tick === before.body.tick + 1);

		// 3. Approve loop: approve → PENDING → IN_TRANSIT → ARRIVED (+ history + SSE)
		console.log('approve loop checks:');
		await j(`${API}/__mock__/reset`, { method: 'POST' });
		const recsBefore = await j(`${API}/api/recommendations`);
		check('seed recommendation is PROPOSED', recsBefore.body[0]?.status === 'PROPOSED');

		const approveRes = await j(`${API}/api/recommendations/1/approve`, { method: 'POST' });
		check('approve returns 200', approveRes.status === 200);
		const recsAfter = await j(`${API}/api/recommendations`);
		check('recommendation now APPROVED', recsAfter.body[0]?.status === 'APPROVED');

		const allocs1 = (await j(`${API}/api/history`)).body.allocations;
		const mine = allocs1.find((a) => a.recommendation_id === 1);
		check('allocation created with idempotency key 1:1', mine?.idempotency_key === '1:1');
		check('allocation starts PENDING', mine?.status === 'PENDING');

		await sleep(2600);
		const mid = (await j(`${API}/api/history`)).body.allocations.find((a) => a.idempotency_key === '1:1');
		check('allocation IN_TRANSIT after ~2.5s', mid?.status === 'IN_TRANSIT');

		await sleep(4000);
		const end = (await j(`${API}/api/history`)).body.allocations.find((a) => a.idempotency_key === '1:1');
		check('allocation ARRIVED after ~6.6s', end?.status === 'ARRIVED');
		check('decision recorded in history', (await j(`${API}/api/history`)).body.decisions.some((d) => d.recommendation_id === 1));

		// double-approve guard: backend 409s; UI must not double-submit anyway
		const reApprove = await j(`${API}/api/recommendations/1/approve`, { method: 'POST' });
		check('double approve 409s', reApprove.status === 409);

		// 4. Stale propagation: banner appears in HTML, approve blocked client-side
		console.log('stale checks:');
		await j(`${API}/__mock__/reset`, { method: 'POST' });
		await j(`${API}/__mock__/stale`, { method: 'POST' });
		const staleHtml = await (await fetch(`${WEB}/recommendations`)).text();
		check('stale banner renders when is_stale', staleHtml.includes('Stale data'));
		await j(`${API}/__mock__/stale`, { method: 'POST' }); // toggle back
		const cleanHtml = await (await fetch(`${WEB}/recommendations`)).text();
		check('stale banner clears', !cleanHtml.includes('Stale data'));

		// 5. Logs endpoint consumed by the Logs tab
		const logs = await j(`${API}/api/logs`);
		check('logs endpoint serves entries', Array.isArray(logs.body) && logs.body.length >= 3);

		console.log(failures === 0 ? '\nALL SMOKE CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
	} finally {
		mock.kill();
		web.kill();
	}
	process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => {
	console.error(e);
	process.exit(1);
});
