<script lang="ts">
	import type { LogEntry } from '$lib/api/types';

	let { logs }: { logs: LogEntry[] } = $props();

	const levelColor = (l: LogEntry['level']) =>
		l === 'ERROR' ? 'var(--sev-critical)' : l === 'WARN' ? 'var(--sev-medium)' : l === 'DEBUG' ? 'var(--text-tertiary)' : 'var(--text-primary)';
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
		font-family: var(--font-mono);
		font-size: var(--text-md);
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		background: var(--surface-muted);
		padding: var(--space-5) 0;
		max-height: 420px;
		overflow-y: auto;
	}
	.line {
		display: flex;
		gap: var(--space-7);
		padding: var(--space-2) var(--space-7);
	}
	.line:hover {
		background: var(--surface-strong);
	}
	.ts {
		color: var(--text-tertiary);
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
		color: var(--text-secondary);
	}
	.msg {
		white-space: pre-wrap;
		word-break: break-word;
	}
	.empty {
		color: var(--text-secondary);
	}
</style>
