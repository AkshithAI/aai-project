/**
 * StepBubble — Renders a single plan step as a chat message bubble.
 *
 * States:
 *  - completed: green checkmark, shows output
 *  - executing: pulsing animation, "currently running"
 *  - pending: dimmed, waiting to be reached
 *  - needs-approval: amber indicator
 */
export default function StepBubble({ step, stepResult, isCurrentStep, isFutureStep }) {
  const isCompleted = !!stepResult;
  const isExecuting = isCurrentStep && !isCompleted;
  const isPending = isFutureStep;
  const needsApproval = step.requires_approval && !isCompleted;

  let statusClass = "pending";
  let statusText = "Pending";
  let statusIcon = "○";

  if (isCompleted) {
    statusClass = "completed";
    statusText = "Completed";
    statusIcon = "✓";
  } else if (isExecuting) {
    statusClass = "executing";
    statusText = "Executing";
    statusIcon = "";
  } else if (needsApproval) {
    statusClass = "pending";
    statusText = "Requires Approval";
    statusIcon = "🛡️";
  }

  return (
    <div className={`step-bubble ${statusClass}`}>
      <div className="step-bubble-avatar">
        {isCompleted ? "✓" : isExecuting ? "⚡" : "🤖"}
      </div>
      <div className="step-bubble-content">
        <div className="step-bubble-label">
          <span className="step-num">{step.index + 1}</span>
          {isExecuting ? "Currently Executing" : isCompleted ? "Step Completed" : "Planned Step"}
          {needsApproval && (
            <span className="plan-step-approval-tag">APPROVAL NEEDED</span>
          )}
        </div>

        <div className="step-bubble-desc">{step.description}</div>

        <div className="step-bubble-tool">
          🔧 {step.tool_name}
        </div>

        {step.tool_args && Object.keys(step.tool_args).length > 0 && (
          <div className="step-bubble-args">
            {JSON.stringify(step.tool_args, null, 2)}
          </div>
        )}

        {isCompleted && stepResult?.output && (
          <div className="step-bubble-output">
            {stepResult.output}
          </div>
        )}

        <div className={`step-bubble-status ${statusClass}`}>
          {isExecuting ? (
            <div className="executing-indicator">
              <div className="executing-dots">
                <span /><span /><span />
              </div>
              Running...
            </div>
          ) : (
            <>
              <span>{statusIcon}</span>
              <span>{statusText}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
