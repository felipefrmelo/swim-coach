const foundations = [
  "Calendário e treinos chegam nas fases seguintes.",
  "A conversa principal acontece no ChatGPT ou Codex.",
  "Nenhum dado Garmin está conectado nesta release P00.",
];

export function App() {
  return (
    <main className="shell">
      <section className="hero" aria-labelledby="page-title">
        <span className="eyebrow">Fundação operacional · P00</span>
        <h1 id="page-title">Swim Coach</h1>
        <p>
          A PWA está pronta para evoluir como superfície operacional, sem duplicar o
          chat do plugin.
        </p>
      </section>

      <section className="status-card" aria-labelledby="status-title">
        <div>
          <span className="status-dot" aria-hidden="true" />
          <span className="status-label">Shell ativo</span>
        </div>
        <h2 id="status-title">Integrações ainda desativadas</h2>
        <ul>
          {foundations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </main>
  );
}
