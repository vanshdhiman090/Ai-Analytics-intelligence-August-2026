import ThemeToggle from "@/components/shell/ThemeToggle";
import { CURRENT_CAPABILITY } from "@/lib/capabilities";

export default function AppShell({ children, capability = CURRENT_CAPABILITY }) {
  return (
    <main className="workspace-page">
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true">AI</div>
        <div className="app-identity">
          <p className="eyebrow">AI Analytics Intelligence</p>
          <h1>{capability.name}</h1>
          <p>{capability.description}</p>
        </div>
        <div className="app-header-actions">
          <div className="capability-status" aria-label="Current capability status">
            <span className="status-indicator" aria-hidden="true" />
            Active capability
          </div>
          <span className="version-badge">{capability.version}</span>
          <ThemeToggle />
        </div>
      </header>
      <div className="app-content">{children}</div>
    </main>
  );
}
