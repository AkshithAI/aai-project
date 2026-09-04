import { useState } from "react";

/**
 * NewChatModal — Modal dialog for creating a new agent run.
 * User enters a task description and optionally adjusts the TTL.
 */

const TTL_PRESETS = [
  { label: "2 min", value: 120 },
  { label: "5 min", value: 300 },
  { label: "1 hour", value: 3600 },
  { label: "1 day", value: 86400 },
];

export default function NewChatModal({ onSubmit, onClose, loading }) {
  const [task, setTask] = useState("");
  const [ttl, setTtl] = useState(3600);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!task.trim()) return;
    onSubmit(task.trim(), ttl);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>
          <span>🚀</span>
          New Agent Run
        </h2>
        <p className="modal-subtitle">
          Describe the task for the AI agent. It will create a plan and execute steps,
          pausing for your approval on consequential actions.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="modal-field">
            <label>Task Description</label>
            <textarea
              placeholder="e.g., Research market trends and send a summary email to the team..."
              value={task}
              onChange={(e) => setTask(e.target.value)}
              autoFocus
            />
          </div>

          <div className="modal-field">
            <label>Approval Window (TTL)</label>
            <input
              type="number"
              min={10}
              max={604800}
              value={ttl}
              onChange={(e) => setTtl(Number(e.target.value))}
            />
            <div className="ttl-presets">
              {TTL_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  className={`ttl-preset-btn ${ttl === p.value ? "active" : ""}`}
                  onClick={() => setTtl(p.value)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={!task.trim() || loading}>
              {loading ? (
                <>
                  <div className="spinner spinner-sm" />
                  Creating...
                </>
              ) : (
                "Create Run"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
