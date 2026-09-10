export function Placeholder({ title, note }: { title: string; note: string }) {
  return (
    <div style={{ padding: "var(--pad-view)" }}>
      <h1
        style={{
          fontSize: "var(--t-display)",
          fontWeight: 500,
          color: "var(--text-0)",
          marginBottom: 14,
        }}
      >
        {title}
      </h1>
      <p style={{ color: "var(--text-2)", maxWidth: 440, lineHeight: 1.7 }}>
        {note}
      </p>
    </div>
  );
}
