import { useEffect, useState } from "react";
import * as api from "../api";

/**
 * Sidebar — Thread list with status indicators and "New Chat" button.
 * Auto-refreshes the thread list every 10 seconds.
 */
export default function Sidebar({ activeThread, onSelectThread, onNewChat }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [backendOnline, setBackendOnline] = useState(true);

  const fetchRuns = async () => {
    try {
      const data = await api.listRuns();
      setRuns(data.runs || []);
      setBackendOnline(true);
    } catch {
      setBackendOnline(false);
    }
  };

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 10000);
    return () => clearInterval(interval);
  }, []);

  // Re-fetch when active thread changes (e.g. after creating a new run)
  useEffect(() => {
    fetchRuns();
  }, [activeThread]);

  // Sort: suspended first, then by recency (thread_id as proxy)
  const sortedRuns = [...runs].sort((a, b) => {
    const order = { pending: 0, suspended: 0, executing: 1, completed: 2, expired: 3, rejected: 4 };
    const aOrder = order[a.status] ?? 5;
    const bOrder = order[b.status] ?? 5;
    if (aOrder !== bOrder) return aOrder - bOrder;
    return (b.suspended_at || "").localeCompare(a.suspended_at || "");
  });

  const formatTtlShort = (seconds) => {
    if (seconds == null || seconds <= 0) return "";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m > 0) return `${m}m`;
    return `${s}s`;
  };

  return (
    <aside className="sidebar">
      {/* Logo / Header */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">⚡</div>
          <div>
            <h1>Durable Agent</h1>
            <div className="sidebar-logo-sub">P27 · Human-in-the-Loop</div>
          </div>
        </div>
        <button className="new-chat-btn" onClick={onNewChat}>
          <span>+</span>
          New Run
        </button>
      </div>

      {/* Thread list */}
      <div className="sidebar-threads">
        <div className="sidebar-section-label">
          Workflows ({sortedRuns.length})
        </div>
        {loading && sortedRuns.length === 0 && (
          <div className="loading-overlay">
            <div className="spinner" />
            Loading...
          </div>
        )}
        {sortedRuns.map((run) => (
          <div
            key={run.thread_id}
            className={`thread-item ${activeThread === run.thread_id ? "active" : ""}`}
            onClick={() => onSelectThread(run.thread_id)}
          >
            <div className="thread-item-header">
              <span className="thread-item-task" title={run.thread_id}>
                {run.thread_id.slice(0, 8)}...
              </span>
              <div className="thread-item-meta">
                {run.status === "pending" && run.time_remaining != null && (
                  <span style={{ fontSize: 11, color: "var(--warning)", fontFamily: "var(--font-mono)" }}>
                    {formatTtlShort(run.time_remaining)}
                  </span>
                )}
                <span className={`status-dot ${run.status === "pending" ? "suspended" : run.status}`} />
              </div>
            </div>
            <div className="thread-item-id">
              <span className={`status-badge ${run.status === "pending" ? "suspended" : run.status}`}>
                {run.status === "pending" ? "suspended" : run.status}
              </span>
            </div>
          </div>
        ))}
        {!loading && sortedRuns.length === 0 && (
          <div style={{ padding: "20px 10px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            No workflows yet.<br />Create a new run to get started.
          </div>
        )}
      </div>

      {/* Footer / Health */}
      <div className="sidebar-footer">
        <span className={`health-dot ${backendOnline ? "" : "offline"}`} />
        {backendOnline ? "Backend online" : "Backend offline"}
      </div>
    </aside>
  );
}
