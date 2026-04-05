/**
 * Santa Meet Bot - Background Service Worker
 *
 * Listens for tab updates to detect Google Meet URLs,
 * sends join/leave requests to the local bot server on port 9877,
 * and manages badge state.
 */

const BOT_SERVER = "http://localhost:9877";

// Bot states
const STATE = { IDLE: "idle", JOINING: "joining", IN_MEETING: "in-meeting" };
let botState = STATE.IDLE;
let activeMeetTabId = null;
let activeMeetUrl = null;

// ---- Badge helpers ----

function setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

function updateBadge() {
  switch (botState) {
    case STATE.JOINING:
      setBadge("...", "#FFA500");
      break;
    case STATE.IN_MEETING:
      setBadge("ON", "#4CAF50");
      break;
    default:
      setBadge("", "#666666");
  }
}

// ---- Server communication ----

async function sendJoin(url) {
  try {
    const resp = await fetch(`${BOT_SERVER}/join`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    return await resp.json();
  } catch (err) {
    console.error("[SantaBot] Join request failed:", err.message);
    return { error: err.message };
  }
}

async function sendLeave() {
  try {
    const resp = await fetch(`${BOT_SERVER}/leave`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    return await resp.json();
  } catch (err) {
    console.error("[SantaBot] Leave request failed:", err.message);
    return { error: err.message };
  }
}

async function fetchStatus() {
  try {
    const resp = await fetch(`${BOT_SERVER}/status`);
    return await resp.json();
  } catch (err) {
    return { state: "unreachable", error: err.message };
  }
}

// ---- Auto-join setting ----

async function isAutoJoinEnabled() {
  const result = await chrome.storage.local.get({ autoJoin: true });
  return result.autoJoin;
}

// ---- Meet URL detection ----

function isMeetUrl(url) {
  if (!url) return false;
  return /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(url);
}

// ---- Core logic ----

async function handleMeetDetected(tabId, url) {
  if (botState !== STATE.IDLE) return;
  const enabled = await isAutoJoinEnabled();
  if (!enabled) return;

  botState = STATE.JOINING;
  activeMeetTabId = tabId;
  activeMeetUrl = url;
  updateBadge();

  const result = await sendJoin(url);
  if (result.error) {
    botState = STATE.IDLE;
    activeMeetTabId = null;
    activeMeetUrl = null;
  } else {
    botState = STATE.IN_MEETING;
  }
  updateBadge();
}

async function handleMeetLeft() {
  if (botState === STATE.IDLE) return;

  await sendLeave();
  botState = STATE.IDLE;
  activeMeetTabId = null;
  activeMeetUrl = null;
  updateBadge();
}

// ---- Tab listeners ----

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url && isMeetUrl(changeInfo.url)) {
    handleMeetDetected(tabId, changeInfo.url);
  }
  // Detect navigation away from Meet on the active tab
  if (
    changeInfo.url &&
    tabId === activeMeetTabId &&
    !isMeetUrl(changeInfo.url)
  ) {
    handleMeetLeft();
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === activeMeetTabId) {
    handleMeetLeft();
  }
});

// ---- Message handler (from content script and popup) ----

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "MEET_JOINED") {
    handleMeetDetected(sender.tab?.id, message.url);
    sendResponse({ ok: true });
  } else if (message.type === "MEET_LEFT") {
    handleMeetLeft();
    sendResponse({ ok: true });
  } else if (message.type === "MANUAL_JOIN") {
    // Force join from popup
    botState = STATE.IDLE; // Reset so handleMeetDetected proceeds
    handleMeetDetected(null, message.url);
    sendResponse({ ok: true });
  } else if (message.type === "MANUAL_LEAVE") {
    handleMeetLeft();
    sendResponse({ ok: true });
  } else if (message.type === "GET_STATE") {
    sendResponse({
      botState,
      activeMeetUrl,
      activeMeetTabId,
    });
  } else if (message.type === "GET_SERVER_STATUS") {
    fetchStatus().then(sendResponse);
    return true; // async
  }
  return false;
});

// Initialize badge
updateBadge();
