import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Fuel Supply Intelligence & Resilience",
  description: "BUP CSE Fest 2026 Hackathon Finals — operator dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#0b0f14", color: "#e6edf3" }}>
        <header
          style={{
            padding: "12px 24px",
            borderBottom: "1px solid #1f2733",
            display: "flex",
            gap: 24,
            alignItems: "center",
          }}
        >
          <strong>Fuel Supply Intelligence</strong>
          <span style={{ color: "#8b949e" }}>Overview · Alerts · Recommendations · History · Health</span>
        </header>
        <main style={{ padding: 24 }}>{children}</main>
      </body>
    </html>
  );
}
