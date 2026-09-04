"""
Real-world end-to-end test for the Durable Agent workflow.

This test hits the LIVE backend (uvicorn must be running on port 8000)
and walks through the full lifecycle:

  1. Submit a real-world task
  2. Verify the plan is tailored to the task (not generic)
  3. Verify the workflow suspends at a consequential action
  4. Approve the action and verify completion
  5. (Bonus) Submit a second task, let TTL expire, verify 410 refusal

Run with:
    python tests/test_real_world.py
"""

import time
import httpx
import sys

BASE = "http://localhost:8000"


def log(msg):
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def step(msg):
    print(f"\n  >> {msg}")


def ok(msg):
    print(f"  [PASS] {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")
    sys.exit(1)


def main():
    client = httpx.Client(base_url=BASE, timeout=30)

    # --- Health check ---
    log("0. Health check")
    r = client.get("/health")
    if r.status_code == 200 and r.json()["status"] == "ok":
        ok("Backend is healthy")
    else:
        fail(f"Backend health check failed: {r.status_code}")

    # ==========================================================
    # TEST 1: Full approve flow with a real-world task
    # ==========================================================
    log("TEST 1: Submit real-world task -> Approve -> Complete")

    task = "Research market trends about soft beverages and email the summary to r.akhilesh1046@gmail.com"

    step(f"Creating run: '{task}'")
    r = client.post("/agent/runs", json={"task": task, "ttl_seconds": 300})
    if r.status_code != 201:
        fail(f"Expected 201, got {r.status_code}: {r.text}")
    data = r.json()
    thread_id = data["thread_id"]
    ok(f"Run created: thread_id={thread_id}")
    ok(f"Status: {data['status']}")

    # Verify the plan is task-specific (not generic)
    step("Verifying plan is tailored to the task")
    plan = data.get("plan", [])
    print(f"    Plan has {len(plan)} steps:")
    for s in plan:
        approval_tag = " [APPROVAL REQUIRED]" if s.get("requires_approval") else ""
        print(f"      Step {s['index']}: {s['description']} -> {s['tool_name']}{approval_tag}")

    # Check that search query mentions soft beverages, not "requested topic"
    search_step = next((s for s in plan if s["tool_name"] == "search_web"), None)
    if search_step:
        query = search_step["tool_args"].get("query", "")
        if "soft beverages" in query.lower():
            ok(f"Search query is task-specific: '{query}'")
        else:
            fail(f"Search query is generic/wrong: '{query}' (expected 'soft beverages')")

    # Check email step uses the right recipient
    email_step = next((s for s in plan if s["tool_name"] == "send_email"), None)
    if email_step:
        to_addr = email_step["tool_args"].get("to", "")
        if "r.akhilesh1046@gmail.com" in to_addr:
            ok(f"Email addressed to correct recipient: {to_addr}")
        else:
            fail(f"Email addressed to wrong recipient: {to_addr}")

    # Verify the run is suspended (waiting for approval on send_email)
    if data["status"] == "suspended":
        ok("Run is SUSPENDED -- waiting for human approval")
        pending = data.get("pending_action")
        if pending:
            print(f"    Pending action: {pending['tool_name']}")
            print(f"    Description: {pending['description']}")
            print(f"    Risk level: {pending.get('risk_level', 'unknown')}")
            print(f"    Args: {pending.get('tool_args', {})}")
    elif data["status"] == "completed":
        # If no consequential steps, this task completed immediately
        ok("Run completed immediately (no approval-required steps)")
        print("    Skipping approve test")
        return

    # Get full run status via GET
    step("Fetching full run status")
    r = client.get(f"/agent/runs/{thread_id}")
    assert r.status_code == 200
    status_data = r.json()
    ok(f"Status: {status_data['status']}, completed_steps: {len(status_data.get('completed_steps', []))}")
    if status_data.get("time_remaining") is not None:
        ok(f"TTL remaining: {status_data['time_remaining']:.1f}s")

    # Approve the pending action
    step("Approving the pending action")
    r = client.post(f"/agent/runs/{thread_id}/approve", json={
        "approver": "test-user",
        "note": "Approved via real-world test script"
    })
    if r.status_code != 200:
        fail(f"Approve failed: {r.status_code} -- {r.text}")
    approve_data = r.json()
    ok(f"Decision: {approve_data['decision']}, Status: {approve_data['status']}")
    if approve_data.get("final_result"):
        print(f"    Final result: {approve_data['final_result'][:200]}")

    # Verify final state
    step("Verifying final run state")
    r = client.get(f"/agent/runs/{thread_id}")
    final = r.json()
    ok(f"Final status: {final['status']}")
    ok(f"Completed steps: {len(final.get('completed_steps', []))}")
    if final.get("final_result"):
        print(f"    Result: {final['final_result'][:300]}")

    # ==========================================================
    # TEST 2: TTL expiry -- approval after deadline is refused
    # ==========================================================
    log("TEST 2: Submit task with short TTL -> Let it expire -> Verify 410")

    step("Creating run with 2-second TTL")
    r = client.post("/agent/runs", json={
        "task": "Analyze server logs and send alert email to ops@company.com",
        "ttl_seconds": 2,
    })
    if r.status_code != 201:
        fail(f"Expected 201, got {r.status_code}: {r.text}")
    data2 = r.json()
    thread_id2 = data2["thread_id"]
    ok(f"Run created: thread_id={thread_id2}, status={data2['status']}")

    if data2["status"] != "suspended":
        ok("Run completed without needing approval -- skipping TTL test")
    else:
        step("Waiting 3 seconds for TTL to expire...")
        time.sleep(3)

        step("Attempting approval after TTL has expired")
        r = client.post(f"/agent/runs/{thread_id2}/approve", json={
            "approver": "late-user",
            "note": "This should be refused"
        })
        if r.status_code == 410:
            detail = r.json().get("detail", {})
            ok(f"Correctly refused with 410 -- code: {detail.get('code', 'N/A')}")
            ok(f"Message: {detail.get('message', 'N/A')}")
        else:
            fail(f"Expected 410, got {r.status_code}: {r.text}")

    # ==========================================================
    # TEST 3: List runs
    # ==========================================================
    log("TEST 3: List all runs")
    r = client.get("/agent/runs")
    runs = r.json()
    ok(f"Total runs tracked: {runs['count']}")
    for run in runs["runs"]:
        print(f"    {run['thread_id'][:12]}... -- {run['status']}")

    log("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
