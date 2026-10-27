import { Component, type ErrorInfo, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import { CutoffProvider } from './context/CutoffContext';
import About from './pages/About';
import Accuracy from './pages/Accuracy';
import Explorer from './pages/Explorer';
import Methodology from './pages/Methodology';
import Overview from './pages/Overview';

/** Catches unexpected render failures so the shell stays usable. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('WindSight render error', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-2xl rounded-lg border border-danger/30 bg-danger/5 p-6">
          <h1 className="text-sm font-semibold text-danger">Something went wrong</h1>
          <p className="mt-2 text-sm text-ink-800">
            The interface hit an unexpected error while rendering.
          </p>
          <pre className="mt-3 overflow-x-auto rounded bg-white p-3 text-xs text-muted">
            {this.state.error.message}
          </pre>
          <button
            type="button"
            className="btn-secondary mt-4"
            onClick={() => window.location.reload()}
          >
            Reload the application
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <CutoffProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="/explorer" element={<Explorer />} />
              <Route path="/accuracy" element={<Accuracy />} />
              <Route path="/methodology" element={<Methodology />} />
              <Route path="/about" element={<About />} />
              <Route path="*" element={<Overview />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </CutoffProvider>
    </ErrorBoundary>
  );
}
