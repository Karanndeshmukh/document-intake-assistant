/**
 * Document Intake Assistant - Client Application
 * Vanilla ES6 JavaScript logic for 3-Panel Synchronization & REST API Integration
 */

// Configure API base URL (uses current origin if served by FastAPI, or fallback to port 8000)
const API_BASE = window.location.port === "8000" 
  ? "" 
  : "http://localhost:8000";

// Application In-Memory State
const appState = {
  sessionId: null,
  messageCount: 0,
  isLoading: false,
};

// DOM Elements Cache
const elements = {
  sessionIdDisplay: document.getElementById("session-id-display"),
  statusPill: document.getElementById("status-pill"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  sendBtn: document.getElementById("send-btn"),
  typingIndicator: document.getElementById("typing-indicator"),
  chatAlert: document.getElementById("chat-alert"),
  messageCountBadge: document.getElementById("message-count-badge"),
  completenessBadge: document.getElementById("completeness-badge"),
  progressBarFill: document.getElementById("progress-bar-fill"),
  
  // State Fields
  valFullName: document.getElementById("val-full-name"),
  statusFullName: document.getElementById("status-full-name"),
  cardFullName: document.getElementById("card-full-name"),

  valHomeAddress: document.getElementById("val-home-address"),
  statusHomeAddress: document.getElementById("status-home-address"),
  cardHomeAddress: document.getElementById("card-home-address"),

  valWorldwideAssets: document.getElementById("val-worldwide-assets"),
  statusWorldwideAssets: document.getElementById("status-worldwide-assets"),
  cardWorldwideAssets: document.getElementById("card-worldwide-assets"),

  valChildren: document.getElementById("val-children"),
  statusChildren: document.getElementById("status-children"),
  cardChildren: document.getElementById("card-children"),

  valExecutorName: document.getElementById("val-executor-name"),
  valExecutorRel: document.getElementById("val-executor-rel"),
  statusExecutor: document.getElementById("status-executor"),
  cardExecutor: document.getElementById("card-executor"),

  valSpecificGifts: document.getElementById("val-specific-gifts"),
  cardGifts: document.getElementById("card-gifts"),

  valAdditionalWishes: document.getElementById("val-additional-wishes"),
  cardWishes: document.getElementById("card-wishes"),

  pendingClarificationBox: document.getElementById("pending-clarification-box"),
  clarificationText: document.getElementById("clarification-text"),

  // Document
  draftDocumentView: document.getElementById("draft-document-view"),
  copyDocBtn: document.getElementById("copy-doc-btn"),
  resetSessionBtn: document.getElementById("reset-session-btn"),
  toast: document.getElementById("toast"),
};

// ============================================================================
// Initialization
// ============================================================================

async function initSession() {
  setLoading(true);
  clearAlert();
  
  try {
    const res = await fetch(`${API_BASE}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });

    if (!res.ok) {
      throw new Error(`Failed to initialize session (HTTP ${res.status})`);
    }

    const data = await res.json();
    appState.sessionId = data.session_id;
    appState.messageCount = 0;

    // UI Updates
    elements.sessionIdDisplay.textContent = data.session_id;
    elements.chatMessages.innerHTML = "";
    
    // Add initial assistant greeting
    appendMessage("assistant", data.initial_message);
    
    // Update live state and document
    updateLiveState(data.state, ["full_name", "home_address", "covers_worldwide_assets", "has_children", "executor_name", "executor_relationship"]);
    updateDocumentPreview(data.draft_document);
    updateStatusPill("in_progress");

  } catch (err) {
    console.error("Session init error:", err);
    showAlert(`Could not connect to the backend server at ${API_BASE || window.location.origin}. Please ensure the FastAPI server is running.`);
  } finally {
    setLoading(false);
  }
}

// ============================================================================
// Messaging & Turn Handling
// ============================================================================

async function handleSendMessage(e) {
  e.preventDefault();
  const text = elements.chatInput.value.trim();
  if (!text || appState.isLoading || !appState.sessionId) return;

  // Append user message immediately
  appendMessage("user", text);
  elements.chatInput.value = "";
  clearAlert();
  setLoading(true);

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: appState.sessionId,
        message: text
      })
    });

    const data = await res.json();

    if (!res.ok) {
      // Backend returned 4xx or 5xx structured error
      const errorMsg = data.assistant_message || data.detail || `Server error (HTTP ${res.status})`;
      appendMessage("assistant", errorMsg);
      if (data.state) {
        updateLiveState(data.state, data.missing_fields || []);
      }
      if (data.draft_document) {
        updateDocumentPreview(data.draft_document);
      }
      updateStatusPill("error");
      return;
    }

    // Normal successful turn
    appendMessage("assistant", data.assistant_message);
    updateLiveState(data.state, data.missing_fields || []);
    updateDocumentPreview(data.draft_document);
    updateStatusPill(data.status);

    // Handle Pending Clarification Notice
    if (data.pending_clarification) {
      elements.pendingClarificationBox.classList.remove("hidden");
      elements.clarificationText.textContent = data.pending_clarification.reason;
    } else {
      elements.pendingClarificationBox.classList.add("hidden");
    }

  } catch (err) {
    console.error("Chat communication error:", err);
    showAlert("Network connection error. Please verify the backend is running and retry.");
  } finally {
    setLoading(false);
    elements.chatInput.focus();
  }
}

// ============================================================================
// Session Reset
// ============================================================================

async function handleResetSession() {
  if (!appState.sessionId) return;
  const confirmed = confirm("Are you sure you want to reset this session? All captured information will be cleared.");
  if (!confirmed) return;

  setLoading(true);
  clearAlert();

  try {
    const res = await fetch(`${API_BASE}/api/session/${appState.sessionId}/reset`, {
      method: "POST"
    });

    if (!res.ok) {
      throw new Error(`Failed to reset session (HTTP ${res.status})`);
    }

    const data = await res.json();
    elements.chatMessages.innerHTML = "";
    appState.messageCount = 0;

    appendMessage("assistant", data.initial_message);
    updateLiveState(data.state, ["full_name", "home_address", "covers_worldwide_assets", "has_children", "executor_name", "executor_relationship"]);
    updateDocumentPreview(data.draft_document);
    updateStatusPill("in_progress");
    elements.pendingClarificationBox.classList.add("hidden");
    showToast("Session reset successfully.");

  } catch (err) {
    console.error("Reset error:", err);
    showAlert("Failed to reset session. Please check backend connection.");
  } finally {
    setLoading(false);
  }
}

// ============================================================================
// UI Renderers
// ============================================================================

function appendMessage(role, text) {
  appState.messageCount += 1;
  elements.messageCountBadge.textContent = `${appState.messageCount} message${appState.messageCount === 1 ? '' : 's'}`;

  const msgDiv = document.createElement("div");
  msgDiv.className = `chat-message message-${role}`;

  const headerDiv = document.createElement("div");
  headerDiv.className = "message-header";
  headerDiv.textContent = role === "user" ? "You" : "Document Assistant";

  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "message-bubble";
  bubbleDiv.textContent = text;

  msgDiv.appendChild(headerDiv);
  msgDiv.appendChild(bubbleDiv);
  elements.chatMessages.appendChild(msgDiv);

  // Auto-scroll to latest
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

function updateLiveState(state, missingFields) {
  if (!state) return;

  // 1. Full Name
  if (state.full_name) {
    elements.valFullName.textContent = state.full_name;
    setFieldStatus(elements.statusFullName, elements.cardFullName, true);
  } else {
    elements.valFullName.innerHTML = "&mdash;";
    setFieldStatus(elements.statusFullName, elements.cardFullName, false);
  }

  // 2. Home Address
  if (state.home_address) {
    elements.valHomeAddress.textContent = state.home_address;
    setFieldStatus(elements.statusHomeAddress, elements.cardHomeAddress, true);
  } else {
    elements.valHomeAddress.innerHTML = "&mdash;";
    setFieldStatus(elements.statusHomeAddress, elements.cardHomeAddress, false);
  }

  // 3. Worldwide Assets
  if (state.covers_worldwide_assets === true) {
    elements.valWorldwideAssets.textContent = "Yes (Worldwide Assets Covered)";
    setFieldStatus(elements.statusWorldwideAssets, elements.cardWorldwideAssets, true);
  } else if (state.covers_worldwide_assets === false) {
    elements.valWorldwideAssets.textContent = "No (Domestic / Local Assets Only)";
    setFieldStatus(elements.statusWorldwideAssets, elements.cardWorldwideAssets, true);
  } else {
    elements.valWorldwideAssets.innerHTML = "&mdash;";
    setFieldStatus(elements.statusWorldwideAssets, elements.cardWorldwideAssets, false);
  }

  // 4. Children
  if (state.has_children === false) {
    elements.valChildren.textContent = "No children";
    setFieldStatus(elements.statusChildren, elements.cardChildren, true);
  } else if (state.has_children === true) {
    if (state.children && state.children.length > 0) {
      elements.valChildren.textContent = `Children: ${state.children.join(", ")}`;
      setFieldStatus(elements.statusChildren, elements.cardChildren, true);
    } else {
      elements.valChildren.textContent = "Has children (Names not yet provided)";
      setFieldStatus(elements.statusChildren, elements.cardChildren, false);
    }
  } else {
    elements.valChildren.innerHTML = "&mdash;";
    setFieldStatus(elements.statusChildren, elements.cardChildren, false);
  }

  // 5. Executor
  const execName = state.executor && state.executor.name;
  const execRel = state.executor && state.executor.relationship;

  elements.valExecutorName.innerHTML = `<strong>Name:</strong> ${execName || "&mdash;"}`;
  elements.valExecutorRel.innerHTML = `<strong>Relationship:</strong> ${execRel || "&mdash;"}`;

  if (execName && execRel) {
    setFieldStatus(elements.statusExecutor, elements.cardExecutor, true);
  } else {
    setFieldStatus(elements.statusExecutor, elements.cardExecutor, false);
  }

  // 6. Specific Gifts
  if (state.specific_gifts && state.specific_gifts.length > 0) {
    elements.valSpecificGifts.innerHTML = state.specific_gifts
      .map((g, i) => `<div>${i + 1}. To <strong>${escapeHtml(g.recipient)}</strong>: ${escapeHtml(g.item_or_amount)}</div>`)
      .join("");
    elements.cardGifts.classList.add("card-confirmed");
  } else {
    elements.valSpecificGifts.innerHTML = "&mdash;";
    elements.cardGifts.classList.remove("card-confirmed");
  }

  // 7. Additional Wishes
  if (state.additional_wishes) {
    elements.valAdditionalWishes.textContent = state.additional_wishes;
    elements.cardWishes.classList.add("card-confirmed");
  } else {
    elements.valAdditionalWishes.innerHTML = "&mdash;";
    elements.cardWishes.classList.remove("card-confirmed");
  }

  // Completeness & Progress Calculation
  const totalMandatory = 6;
  const remainingMissing = missingFields ? missingFields.length : 0;
  const completedCount = Math.max(0, totalMandatory - remainingMissing);
  const percentage = Math.round((completedCount / totalMandatory) * 100);

  elements.progressBarFill.style.width = `${percentage}%`;
  elements.completenessBadge.textContent = `${completedCount} / ${totalMandatory} Required`;

  if (completedCount === totalMandatory) {
    elements.completenessBadge.className = "badge badge-success";
  } else {
    elements.completenessBadge.className = "badge badge-warning";
  }
}

function setFieldStatus(statusEl, cardEl, isConfirmed) {
  if (isConfirmed) {
    statusEl.textContent = "Confirmed";
    statusEl.className = "field-status status-confirmed";
    cardEl.classList.add("card-confirmed");
  } else {
    statusEl.textContent = "Required";
    statusEl.className = "field-status status-empty";
    cardEl.classList.remove("card-confirmed");
  }
}

function updateDocumentPreview(docText) {
  if (docText) {
    elements.draftDocumentView.textContent = docText;
  }
}

function updateStatusPill(status) {
  elements.statusPill.className = "status-pill";
  if (status === "complete") {
    elements.statusPill.textContent = "Ready / Complete";
    elements.statusPill.classList.add("status-complete");
  } else if (status === "contradiction_detected") {
    elements.statusPill.textContent = "Contradiction";
    elements.statusPill.classList.add("status-contradiction");
  } else if (status === "clarification_needed") {
    elements.statusPill.textContent = "Clarification Needed";
    elements.statusPill.classList.add("status-clarification");
  } else if (status === "error") {
    elements.statusPill.textContent = "System Error";
    elements.statusPill.classList.add("status-contradiction");
  } else {
    elements.statusPill.textContent = "In Progress";
    elements.statusPill.classList.add("status-in-progress");
  }
}

function setLoading(loading) {
  appState.isLoading = loading;
  elements.sendBtn.disabled = loading;
  elements.chatInput.disabled = loading;
  if (loading) {
    elements.typingIndicator.classList.remove("hidden");
  } else {
    elements.typingIndicator.classList.add("hidden");
  }
}

function showAlert(text) {
  elements.chatAlert.textContent = text;
  elements.chatAlert.classList.remove("hidden");
}

function clearAlert() {
  elements.chatAlert.textContent = "";
  elements.chatAlert.classList.add("hidden");
}

function showToast(text) {
  elements.toast.textContent = text;
  elements.toast.classList.remove("hidden");
  setTimeout(() => {
    elements.toast.classList.add("hidden");
  }, 2500);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ============================================================================
// Event Listeners
// ============================================================================

elements.chatForm.addEventListener("submit", handleSendMessage);
elements.resetSessionBtn.addEventListener("click", handleResetSession);

elements.copyDocBtn.addEventListener("click", () => {
  const docText = elements.draftDocumentView.textContent;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(docText).then(() => {
      showToast("Draft document copied to clipboard!");
    }).catch(() => {
      showToast("Failed to copy automatically.");
    });
  } else {
    showToast("Clipboard API unavailable.");
  }
});

// Auto-run on page load
window.addEventListener("DOMContentLoaded", initSession);
