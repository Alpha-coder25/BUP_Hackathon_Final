<script lang="ts">
	import type { LogEntry } from '$lib/api/types';

	let { logs }: { logs: LogEntry[] } = $props();

	const levelColor = (l: LogEntry['level']) =>
		l === 'ERROR' ? 'var(--sev-critical)' : l === 'WARN' ? 'var(--sev-medium)' : l === 'DEBUG' ? 'var(--muted)' : 'var(--text)';
</script>

{#if logs.length === 0}
	<p class="empty">No log events yet.</p>
{:else}
	<div class="logs">
		{#each logs as entry (entry.ts + entry.message)}
			<div class="line">
				<span class="ts">{entry.ts}</span>
				<span class="level" style:color={levelColor(entry.level)}>{entry.level}</span>
				<span class="comp">{entry.component}</span>
				<span class="msg">{entry.message}</span>
			</div>
		{/each}
	</div>
{/if}

<style>
	.logs {
		font-family: ui-monospace, 'Cascadia Code', Menlo, monospace;
		font-size: 0.75rem;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--panel);
		padding: 0.5rem 0;
		max-height: 420px;
		overflow-y: auto;
	}
	.line {
		display: flex;
		gap: 0.7rem;
		padding: 0.15rem 0.75rem;
	}
	.ts {
		color: var(--muted);
		flex-shrink: 0;
	}
	.level {
		width: 3.5rem;
		flex-shrink: 0;
		font-weight: 600;
	}
	.comp {
		width: 6rem;
		flex-shrink: 0;
		color: var(--muted);
	}
	.msg {
		white-space: pre-wrap;
		word-break: break-word;
	}
	.empty {
		color: var(--muted);
	}
</style>
