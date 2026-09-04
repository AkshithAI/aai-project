import { useState, useEffect, useRef } from "react";
import * as api from "../api";

/**
 * Format seconds into a human-readable countdown string.
 */
function formatTimeRemaining(seconds) {
  if (seconds == null || seconds <= 0) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/**
 * Get TTL urgency class based on remaining time.
 */
function getTtlClass(remaining) {
  if (remaining == null) return "";
  if (remaining <= 60) return "danger";
  if (remaining <= 300) return "warning";
  return "";
}

/**
 * ApprovalCard — The human-in-the-loop approval interface.
 * Renders when a workflow is suspended and awaiting human decision.
 */
export default function ApprovalCard({ pendingAction, timeRemaining, threadId, onDecision }) {
  const [mode, setMode] = useState(null); // null | "approve" | "reject"
  const [approver, setApprover] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [countdown, setCountdown] = useState(timeRemaining);
  const intervalRef = useRef(null);

  // Live countdown timer
  useEffect(() => {
    setCountdown(timeRemaining);
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (timeRemaining != null && timeRemaining > 0) {
      intervalRef.current = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            clearInterval(intervalRef.current);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return () => clearInterval(intervalRef.current);
  }, [timeRemaining]);

  const handleApprove = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.approveRun(threadId, approver || "user", note);
      onDecision("approved", result);
    } catch (err) {
      if (err.code === "TTL_EXCEEDED") {
        setError("⏱ The approval window has expired. This action can no longer be approved.");
        onDecision("expired", null);
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.rejectRun(threadId, approver || "user", reason);
      onDecision("rejected", result);
    } catch (err) {
      if (err.code === "TTL_EXCEEDED") {
        setError("⏱ The approval window has expired.");
        onDecision("expired", null);
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  if (!pendingAction) return null;

  const isExpired = countdown != null && countdown <= 0;

  return (
    <div className="approval-card-wrapper">
      <div className="step-bubble-avatar" style={{ background: "linear-gradient(135deg, #f59e0b, #f97316)" }}>
        ⚠️
      </div>
      <div className="approval-card">
        {/* Header */}
        <div className="approval-card-header">
          <div className="approval-card-title">
            <span className="icon">🛡️</span>
            Human Approval Required
          </div>
          <span className={`risk-badge ${pendingAction.risk_level || "medium"}`}>
            {pendingAction.risk_level || "medium"} risk
          </span>
        </div>

        {/* Action details */}
        <div className="approval-action-detail">
          <p className="approval-action-desc">{pendingAction.description}</p>
          <div className="approval-tool-info">
            <span className="approval-tool-name">🔧 {pendingAction.tool_name}</span>
          </div>
          {pendingAction.tool_args && Object.keys(pendingAction.tool_args).length > 0 && (
            <div className="approval-tool-args">
              {JSON.stringify(pendingAction.tool_args, null, 2)}
            </div>
          )}
        </div>

        {/* TTL Countdown */}
        {countdown != null && (
          <div className={`approval-ttl ${getTtlClass(countdown)}`}>
            <span className="ttl-icon">⏱️</span>
            <span>Approval window:</span>
            <span className="ttl-value">{formatTimeRemaining(countdown)}</span>
            {isExpired && <span style={{ marginLeft: "auto", color: "var(--danger)" }}>EXPIRED</span>}
          </div>
        )}

        {isExpired ? (
          <div className="expired-card">
            <div className="expired-icon">⏰</div>
            <h4>Approval Window Expired</h4>
            <p>The TTL for this action has been exceeded. The workflow will follow the expiry path.</p>
          </div>
        ) : (
          <>
            {/* Approval / Rejection form */}
            {mode === null && (
              <div className="approval-buttons">
                <button className="btn btn-approve" onClick={() => setMode("approve")} disabled={loading}>
                  ✓ Approve
                </button>
                <button className="btn btn-reject" onClick={() => setMode("reject")} disabled={loading}>
                  ✕ Reject
                </button>
              </div>
            )}

            {mode === "approve" && (
              <div className="approval-form">
                <div className="approval-input-group">
                  <label>Your Name</label>
                  <input
                    type="text"
                    placeholder="Enter your name..."
                    value={approver}
                    onChange={(e) => setApprover(e.target.value)}
                  />
                </div>
                <div className="approval-input-group">
                  <label>Note (optional)</label>
                  <textarea
                    placeholder="Add a note about this approval..."
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </div>
                <div className="approval-buttons">
                  <button className="btn btn-approve" onClick={handleApprove} disabled={loading}>
                    {loading ? <><div className="spinner spinner-sm" /> Processing...</> : "✓ Confirm Approval"}
                  </button>
                  <button className="btn btn-ghost" onClick={() => setMode(null)} disabled={loading}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {mode === "reject" && (
              <div className="approval-form">
                <div className="approval-input-group">
                  <label>Your Name</label>
                  <input
                    type="text"
                    placeholder="Enter your name..."
                    value={approver}
                    onChange={(e) => setApprover(e.target.value)}
                  />
                </div>
                <div className="approval-input-group">
                  <label>Reason for Rejection</label>
                  <textarea
                    placeholder="Why are you rejecting this action?"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </div>
                <div className="approval-buttons">
                  <button className="btn btn-reject" onClick={handleReject} disabled={loading}>
                    {loading ? <><div className="spinner spinner-sm" /> Processing...</> : "✕ Confirm Rejection"}
                  </button>
                  <button className="btn btn-ghost" onClick={() => setMode(null)} disabled={loading}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {error && <div className="error-toast" style={{ marginTop: 12 }}>⚠ {error}</div>}
      </div>
    </div>
  );
}
