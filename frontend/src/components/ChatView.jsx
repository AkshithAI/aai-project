import { useEffect, useState, useRef } from "react";
import * as api from "../api";
import StepBubble from "./StepBubble";
import ApprovalCard from "./ApprovalCard";

/**
 * ChatView — Main chat-style area showing the agent workflow.
 *
 * Displays:
 *  - Plan overview (all steps at a glance)
 *  - Step bubbles for each plan step (completed, executing, pending)
 *  - ApprovalCard when suspended
 *  - User action bubbles for approve/reject decisions
 *  - Final result or error at the end
 */
export default function ChatView({ threadId }) {
  const [runData, setRunData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userActions, setUserActions] = useState([]); // track approve/reject actions in this session
  const messagesEndRef = useRef(null);
  const pollRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const fetchRun = async () => {
    try {
      const data = await api.getRun(threadId);
      setRunData(data);
      setError(null);

      // Keep polling if still executing or just approved
      if (data.status === "executing" || data.status === "suspended") {
        // continue polling
      } else {
        // Stop polling when terminal state
        clearInterval(pollRef.current);
      }
    } catch (err) {
      setError(err.message);
      clearInterval(pollRef.current);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!threadId) return;
    setLoading(true);
    setRunData(null);
    setUserActions([]);
    setError(null);
    fetchRun();

    // Poll every 3 seconds for live updates
    pollRef.current = setInterval(fetchRun, 3000);
    return () => clearInterval(pollRef.current);
  }, [threadId]);

  // Scroll to bottom when new content appears
  useEffect(() => {
    scrollToBottom();
  }, [runData, userActions]);

  const handleDecision = (decision, result) => {
    setUserActions((prev) => [
      ...prev,
      { decision, result, timestamp: new Date().toISOString() },
    ]);
    // Refresh run data after decision
    setTimeout(fetchRun, 500);

    // If the result says still suspended (multi-step approval), keep polling
    if (result?.status === "suspended") {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(fetchRun, 3000);
    }
  };

  if (!threadId) return null;

  if (loading && !runData) {
    return (
      <div className="chat-view">
        <div className="chat-header">
          <div className="chat-header-left">
            <span className="chat-header-title">Loading...</span>
          </div>
        </div>
        <div className="chat-messages">
          <div className="loading-overlay">
            <div className="spinner" />
            Loading workflow...
          </div>
        </div>
      </div>
    );
  }

  if (error && !runData) {
    return (
      <div className="chat-view">
        <div className="chat-header">
          <div className="chat-header-left">
            <span className="chat-header-title">Error</span>
          </div>
        </div>
        <div className="chat-messages">
          <div className="error-toast">⚠ {error}</div>
        </div>
      </div>
    );
  }

  if (!runData) return null;

  const { status, task, plan, current_step, completed_steps, pending_action, final_result, time_remaining, approval_decision } = runData;

  // Build a lookup from step index to result
  const stepResultMap = {};
  (completed_steps || []).forEach((r) => {
    stepResultMap[r.step_index] = r;
  });

  // Determine if we should show the approval card (suspended + pending action + not yet acted upon in this session)
  const showApproval = status === "suspended" && pending_action != null;

  return (
    <div className="chat-view">
      {/* Header */}
      <div className="chat-header">
        <div className="chat-header-left">
          <span className="chat-header-title">Workflow</span>
          <span className="chat-header-id">{threadId.slice(0, 12)}...</span>
          <span className={`status-badge ${status}`}>{status}</span>
        </div>
        <div className="chat-header-right">
          {time_remaining != null && status === "suspended" && (
            <span className="approval-ttl" style={{ margin: 0, padding: "4px 10px" }}>
              <span className="ttl-icon">⏱️</span>
              <span className="ttl-value" style={{ fontSize: 12 }}>
                {formatTTL(time_remaining)}
              </span>
            </span>
          )}
        </div>
      </div>

      {/* Chat messages */}
      <div className="chat-messages">
        {/* Task announcement */}
        <div className="step-bubble">
          <div className="user-avatar">👤</div>
          <div className="step-bubble-content" style={{ background: "linear-gradient(135deg, rgba(59,130,246,0.08), rgba(139,92,246,0.05))", borderColor: "rgba(59,130,246,0.15)" }}>
            <div className="step-bubble-label">Task Submitted</div>
            <div className="step-bubble-desc">{task}</div>
          </div>
        </div>

        {/* Plan overview */}
        {plan && plan.length > 0 && (
          <div className="plan-overview">
            <div className="step-bubble-avatar">📋</div>
            <div className="plan-overview-content">
              <h3>
                <span>📋</span>
                Execution Plan — {plan.length} step{plan.length !== 1 ? "s" : ""}
              </h3>
              <ul className="plan-step-list">
                {plan.map((step, i) => {
                  const isCompleted = !!stepResultMap[i];
                  const isActive = i === current_step && !isCompleted && status !== "completed";
                  const needsApproval = step.requires_approval && !isCompleted;
                  return (
                    <li
                      key={i}
                      className={`plan-step-item ${isCompleted ? "completed" : ""} ${isActive ? "active" : ""} ${needsApproval ? "needs-approval" : ""}`}
                    >
                      <span className="plan-step-num">
                        {isCompleted ? "✓" : i + 1}
                      </span>
                      <span className="plan-step-desc">{step.description}</span>
                      {needsApproval && (
                        <span className="plan-step-approval-tag">APPROVAL</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        )}

        {/* Step-by-step execution bubbles (only for completed + current) */}
        {plan && plan.map((step, i) => {
          const stepResult = stepResultMap[i];
          const isCurrentStep = i === current_step;
          const isFutureStep = i > current_step;

          // Only show completed steps and the current step
          if (!stepResult && !isCurrentStep) return null;
          // Don't show if we're past completion
          if (status === "completed" && !stepResult) return null;

          return (
            <StepBubble
              key={i}
              step={step}
              stepResult={stepResult}
              isCurrentStep={isCurrentStep && status !== "completed" && status !== "expired" && status !== "rejected"}
              isFutureStep={false}
            />
          );
        })}

        {/* User action bubbles for past decisions in this session */}
        {userActions.map((action, i) => (
          <div key={`action-${i}`} className="user-action-bubble">
            <div className={`user-action-content ${action.decision}`}>
              <div className="user-action-label">Your Decision</div>
              <div className="user-action-text">
                {action.decision === "approved"
                  ? "✓ Approved the action"
                  : action.decision === "rejected"
                  ? "✕ Rejected the action"
                  : "⏱ Action expired"}
              </div>
            </div>
            <div className="user-avatar">👤</div>
          </div>
        ))}

        {/* Approval Card */}
        {showApproval && (
          <ApprovalCard
            pendingAction={pending_action}
            timeRemaining={time_remaining}
            threadId={threadId}
            onDecision={handleDecision}
          />
        )}

        {/* Expired state */}
        {(status === "expired" || approval_decision === "expired") && (
          <div className="approval-card-wrapper">
            <div className="step-bubble-avatar" style={{ background: "linear-gradient(135deg, #ef4444, #dc2626)" }}>
              ⏰
            </div>
            <div className="expired-card">
              <div className="expired-icon">⏰</div>
              <h4>Approval Window Expired — TTL Exceeded</h4>
              <p>
                The bounded time-to-live for this approval request has been exceeded.
                The workflow has followed the expiry path. Status code: <strong>TTL_EXCEEDED (410)</strong>
              </p>
            </div>
          </div>
        )}

        {/* Final result */}
        {final_result && (
          <div className="final-result">
            <div className="step-bubble-avatar" style={{
              background: status === "completed" && approval_decision !== "rejected" && approval_decision !== "expired"
                ? "linear-gradient(135deg, #22c55e, #06b6d4)"
                : "linear-gradient(135deg, #ef4444, #f97316)"
            }}>
              {status === "completed" && approval_decision !== "rejected" && approval_decision !== "expired" ? "✅" : "⛔"}
            </div>
            <div className={`final-result-content ${approval_decision === "rejected" ? "rejected" : ""} ${approval_decision === "expired" || status === "expired" ? "expired" : ""}`}>
              <h4>
                {status === "completed" && approval_decision !== "rejected" && approval_decision !== "expired"
                  ? <>✅ Workflow Completed</>
                  : approval_decision === "rejected"
                  ? <>⛔ Workflow Rejected</>
                  : <>⏰ Workflow Expired</>
                }
              </h4>
              <pre className="final-result-text">{final_result}</pre>
            </div>
          </div>
        )}

        {/* Error */}
        {runData.error && !final_result && (
          <div className="error-toast">⚠ {runData.error}</div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}

function formatTTL(seconds) {
  if (seconds == null || seconds <= 0) return "Expired";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
