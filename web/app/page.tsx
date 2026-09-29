"use client";

import { useEffect, useState } from "react";

type Components = Record<string, { status: string; detail?: string | object }>;

export default function Overview() {
  const [state, setState] = useState<object | null>(null);
  const [health, setHealth] = useState<Components | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
    const load = async () => {
      try {
        const [s, h] = await Promise.all([
          fetch(`${api}/api/state`).then((r) => r.json()),
          fetch(`${api}/health`).then((r) => r.json()),
        ]);
        setState(s);
        setHealth(h.components);
        setError(null);
      } catch {
        setError("Backend unreachable");
      }
    };
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const badge = (s?: string) =>
    s === "HEALTHY" ? "#2ea043" : s === "DOWN" ? "#f85149" : "#d29922";

  return (
    <div>
      {error && <p style={{ color: "#f85149" }}>{error}</p>}
      <section style={{ display: "flex", gap: 12, marginBottom: 24 }}>
        {health &&
          Object.entries(health).map(([name, c]) => (
            <div key={name} style={{ border: "1px solid #1f2733", borderRadius: 8, padding: "8px 16px" }}>
              <span style={{ color: badge(c.status) }}>●</span> {name}: {c.status}
            </div>
          ))}
      </section>
      <section>
        <h2>Network state</h2>
        <pre style={{ background: "#11161d", padding: 16, borderRadius: 8, overflow: "auto", fontSize: 12 }}>
          {state ? JSON.stringify(state, null, 2) : "Waiting for collector data…"}
        </pre>
      </section>
    </div>
  );
}
