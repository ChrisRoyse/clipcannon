/**
 * Santa Meet Bot - Popup UI logic
 */

const botStatusEl = document.getElementById("botStatus");
const serverStatusEl = document.getElementById("serverStatus");
const meetingUrlRow = document.getElementById("meetingUrlRow");
const meetingUrlEl = document.getElementById("meetingUrl");
const autoJoinToggle = document.getElementById("autoJoinToggle");
const meetUrlInput = document.getElementById("meetUrl");
const joinBtn = document.getElementById("joinBtn");
const leaveBtn = document.getElementById("leaveBtn");

function setStatusClass(el, state) {
  el.className = "status-value " + state;
}

function updateUI(botState, activeMeetUrl, serverState) {
  // Bot status
  const stateLabels = {
    idle: "Idle",
    joining: "Joining...",
    "in-meeting": "In Meeting",
  };
  botStatusEl.textContent = stateLabels[botState] || botState;
  setStatusClass(botStatusEl, botState);

  // Server status
  if (serverState === "unreachable") {
    serverStatusEl.textContent = "Offline";
    setStatusClass(serverStatusEl, "unreachable");
  } else {
    serverStatusEl.textContent = "Online";
    setStatusClass(serverStatusEl, "in-meeting");
  }

  // Meeting URL
  if (activeMeetUrl) {
    meetingUrlRow.style.display = "flex";
    meetingUrlEl.textContent = activeMeetUrl;
  } else {
    meetingUrlRow.style.display = "none";
  }

  // Buttons
  joinBtn.disabled = botState !== "idle";
  leaveBtn.disabled = botState === "idle";
}

// Load auto-join setting
chrome.storage.local.get({ autoJoin: true }, (result) => {
  autoJoinToggle.checked = result.autoJoin;
});

// Save auto-join setting on toggle
autoJoinToggle.addEventListener("change", () => {
  chrome.storage.local.set({ autoJoin: autoJoinToggle.checked });
});

// Fetch current state from background
function refresh() {
  chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp) => {
    if (chrome.runtime.lastError || !resp) return;
    chrome.runtime.sendMessage({ type: "GET_SERVER_STATUS" }, (srvResp) => {
      const serverState = srvResp?.error ? "unreachable" : "online";
      updateUI(resp.botState, resp.activeMeetUrl, serverState);
    });
  });
}

// Manual join
joinBtn.addEventListener("click", () => {
  const url = meetUrlInput.value.trim();
  if (!url) {
    meetUrlInput.focus();
    return;
  }
  // Basic validation
  if (!/^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(url)) {
    meetUrlInput.style.borderColor = "#f44336";
    setTimeout(() => { meetUrlInput.style.borderColor = "#3a3a5a"; }, 1500);
    return;
  }
  chrome.runtime.sendMessage({ type: "MANUAL_JOIN", url }, () => {
    setTimeout(refresh, 500);
  });
});

// Manual leave
leaveBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "MANUAL_LEAVE" }, () => {
    setTimeout(refresh, 500);
  });
});

// Initial load
refresh();

// Refresh periodically while popup is open
setInterval(refresh, 3000);
