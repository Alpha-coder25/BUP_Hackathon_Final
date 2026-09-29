// Formatting helpers — liters, ticks→hours, severity classes (FrontendImplementation §5).

export const fmtLiters = (n: number) =>
	new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(n) + ' L';

export const fmtHours = (h: number) => `${h.toFixed(1)} h`;

export const severityVar = (s: string) =>
	`var(--sev-${s.toLowerCase()})`; // --sev-low | --sev-medium | --sev-high | --sev-critical

export const policyLabel = (p: string) =>
	({ optimizer: 'OPTIMIZER', heuristic: 'HEURISTIC', fallback: 'FALLBACK' })[p] ?? p.toUpperCase();
