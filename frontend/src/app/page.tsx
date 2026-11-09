export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 px-6 py-12 text-slate-100">
      <div className="mx-auto max-w-5xl">
        <header className="mb-10 flex items-center justify-between border-b border-slate-800 pb-4">
          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-blue-400">PayRecon AI</p>
            <h1 className="mt-3 text-4xl font-bold">Monitoring & reconciliation foundation</h1>
          </div>
        </header>

        <section className="grid gap-6 md:grid-cols-3">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-lg font-semibold text-blue-400">Payments</h2>
            <p className="mt-3 text-slate-300">Normalized PayPal transaction stream and capture pipeline.</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-lg font-semibold text-blue-400">Reconciliation</h2>
            <p className="mt-3 text-slate-300">Anomaly, mismatch, and exception detection boundaries.</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-lg font-semibold text-blue-400">Investigations</h2>
            <p className="mt-3 text-slate-300">Evidence-backed AI recommendations and follow-up workflows.</p>
          </div>
        </section>
      </div>
    </main>
  );
}
