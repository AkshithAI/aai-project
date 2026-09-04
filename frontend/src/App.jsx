import { useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import NewChatModal from "./components/NewChatModal";
import * as api from "./api";
import "./index.css";

/**
 * App — Root layout with sidebar + main chat area.
 */
export default function App() {
  const [activeThread, setActiveThread] = useState(null);
  const [showNewChat, setShowNewChat] = useState(false);
  const [creating, setCreating] = useState(false);

  const handleNewChat = async (task, ttl) => {
    setCreating(true);
    try {
      const result = await api.createRun(task, ttl);
      setActiveThread(result.thread_id);
      setShowNewChat(false);
    } catch (err) {
      alert("Failed to create run: " + err.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="app-layout">
      <Sidebar
        activeThread={activeThread}
        onSelectThread={setActiveThread}
        onNewChat={() => setShowNewChat(true)}
      />

      <div className="main-content">
        {activeThread ? (
          <ChatView threadId={activeThread} />
        ) : (
          <div className="empty-state">
            <div className="empty-icon">⚡</div>
            <h2>Durable Agent Workflow</h2>
            <p>
              Create a new agent run to start an AI workflow with human-in-the-loop
              approval gates. Your workflows survive restarts and enforce
              TTL-bounded approval windows.
            </p>
            <button className="new-chat-btn" onClick={() => setShowNewChat(true)}>
              <span>+</span>
              Create New Run
            </button>
          </div>
        )}
      </div>

      {showNewChat && (
        <NewChatModal
          onSubmit={handleNewChat}
          onClose={() => setShowNewChat(false)}
          loading={creating}
        />
      )}
    </div>
  );
}
