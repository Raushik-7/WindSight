import { ExternalLink, Github, User } from 'lucide-react';

const PROFILE = {
  name: 'Raushik Gupta',
  role: 'Full-Stack Developer and Computer Science student',
  education: 'B.Tech in Computer Science and Engineering, VIT Bhopal University',
  summary:
    'Raushik Gupta is a Computer Science student at VIT Bhopal University and a full-stack developer interested in building reliable, scalable software systems. He approaches projects by first understanding the architecture, high-level design, low-level design, data flow, and system constraints before moving into implementation. His interests include backend engineering, API design, data processing, system design, and building practical software products.',
  portfolio: 'https://raushik-portfolio.vercel.app',
  github: 'https://github.com/Raushik-7',
};

const CONTRIBUTIONS = [
  {
    title: 'Data correctness',
    body: 'Cutoff-aware forecast selection, timezone-safe timestamp handling, explicit missing-data statuses and metric sample counts, all covered by unit tests with hand-calculated expectations.',
  },
  {
    title: 'Backend architecture',
    body: 'A FastAPI service split into an Elexon client, normalisation, selection, matching, metrics, caching and export modules so business logic stays independent of HTTP handlers.',
  },
  {
    title: 'Frontend craft',
    body: 'A React + TypeScript dashboard with a restrained design system, loading/error/empty states, keyboard-accessible navigation and charts backed strictly by API responses.',
  },
  {
    title: 'Reproducibility',
    body: 'Docker Compose setup, committed real-data snapshots, documented environment variables and an AI-usage disclosure in the README.',
  },
];

export default function About() {
  return (
    <div className="space-y-6">
      <header className="card p-5">
        <p className="label-caps">About the developer</p>
        <h1 className="mt-1 text-xl font-semibold text-ink-900 sm:text-2xl">{PROFILE.name}</h1>
        <p className="mt-1 text-sm text-muted">{PROFILE.role}</p>
        <p className="mt-1 text-sm text-muted">{PROFILE.education}</p>
      </header>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <article className="card p-5 lg:col-span-2">
          <div className="flex items-center gap-2">
            <User className="h-4 w-4 text-muted" aria-hidden="true" />
            <h2 className="text-sm font-semibold text-ink-900">Professional summary</h2>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-ink-800">{PROFILE.summary}</p>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            WindSight demonstrates his interest in data-driven engineering, API integration,
            analytical correctness, and full-stack product development: it retrieves real Elexon
            BMRS records, applies a documented forecast-selection policy, quantifies forecast error
            against actual outturn, and presents the results in an interface a procurement team can
            actually use.
          </p>

          <div className="mt-5 flex flex-wrap gap-3">
            <a className="btn-primary" href={PROFILE.portfolio} target="_blank" rel="noreferrer">
              Portfolio <ExternalLink className="h-4 w-4" aria-hidden="true" />
            </a>
            <a className="btn-secondary" href={PROFILE.github} target="_blank" rel="noreferrer">
              <Github className="h-4 w-4" aria-hidden="true" />
              GitHub profile
            </a>
          </div>
        </article>

        <aside className="card p-5">
          <h2 className="text-sm font-semibold text-ink-900">This project at a glance</h2>
          <dl className="mt-3 space-y-3 text-sm">
            <div>
              <dt className="label-caps">Stack</dt>
              <dd className="mt-1 text-ink-800">React, TypeScript, Vite, Tailwind CSS, Recharts · Python, FastAPI, Pydantic · Docker</dd>
            </div>
            <div>
              <dt className="label-caps">Data</dt>
              <dd className="mt-1 text-ink-800">Elexon BMRS FUELHH (actual outturn) and WINDFOR (published forecasts)</dd>
            </div>
            <div>
              <dt className="label-caps">Period</dt>
              <dd className="mt-1 text-ink-800">01–31 January 2026, delivery-date based (1,488 half-hourly intervals)</dd>
            </div>
            <div>
              <dt className="label-caps">Scope</dt>
              <dd className="mt-1 text-ink-800">
                Read-only historical forecast evaluation. WindSight does not forecast wind itself,
                price electricity, or place trades.
              </dd>
            </div>
          </dl>
        </aside>
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {CONTRIBUTIONS.map((item) => (
          <article key={item.title} className="card p-5">
            <h3 className="text-sm font-semibold text-ink-900">{item.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-muted">{item.body}</p>
          </article>
        ))}
      </section>
    </div>
  );
}
