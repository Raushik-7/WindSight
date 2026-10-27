import type { ReactNode } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  Gauge,
  Info,
  Waves,
} from 'lucide-react';

const NAV = [
  { to: '/', label: 'Overview', icon: Gauge, end: true },
  { to: '/explorer', label: 'Forecast Explorer', icon: Activity, end: false },
  { to: '/accuracy', label: 'Accuracy Analysis', icon: BarChart3, end: false },
  { to: '/methodology', label: 'Methodology & Data', icon: BookOpen, end: false },
  { to: '/about', label: 'About the Developer', icon: Info, end: false },
];

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <span className="grid h-9 w-9 place-items-center rounded-md bg-accent/15 text-accent">
        <Waves className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <p className="text-lg font-semibold leading-none text-white">WindSight</p>
        <p className="mt-1 text-[11px] leading-tight text-white/60">
          Wind forecast intelligence
        </p>
      </div>
    </div>
  );
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary">
      <ul className="flex flex-col gap-1">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-white/10 font-medium text-white'
                    : 'text-white/70 hover:bg-white/5 hover:text-white',
                ].join(' ')
              }
            >
              <item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/**
 * Application shell: navy sidebar on desktop, compact top bar on smaller
 * screens. The evaluation-period indicator is always visible.
 */
export default function Layout({ children }: { children?: ReactNode }) {
  return (
    <div className="min-h-screen lg:flex">
      <header className="bg-ink-900 text-white lg:sticky lg:top-0 lg:h-screen lg:w-64 lg:shrink-0 lg:flex lg:flex-col">
        <div className="flex items-center justify-between gap-4 px-4 py-4 lg:px-5 lg:py-6">
          <Brand />
          <span className="hidden rounded border border-white/20 px-2 py-1 text-[11px] text-white/70 lg:inline-block">
            Jan 2026
          </span>
        </div>

        <div className="hidden px-5 pb-4 lg:block">
          <div className="rounded-md border border-white/10 bg-white/5 px-3 py-2">
            <p className="label-caps text-white/50">Evaluation period</p>
            <p className="mt-1 text-sm text-white">01–31 January 2026</p>
            <p className="mt-1 text-[11px] text-white/50">
              Delivery-date based · 1,488 intervals
            </p>
          </div>
        </div>

        <div className="px-3 py-4 lg:px-3">
          <NavItems />
        </div>

        <div className="mt-auto hidden border-t border-white/10 px-5 py-4 lg:block">
          <p className="flex items-center gap-2 text-[11px] text-white/50">
            <Database className="h-3.5 w-3.5" aria-hidden="true" />
            Source: Elexon BMRS (FUELHH, WINDFOR)
          </p>
        </div>
      </header>

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children ?? <Outlet />}
        </div>
      </main>
    </div>
  );
}
