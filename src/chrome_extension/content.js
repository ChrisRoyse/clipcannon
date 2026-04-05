/**
 * Santa Meet Bot - Content Script for Google Meet pages
 *
 * Detects meeting state transitions (lobby, in-meeting, left)
 * and notifies the background service worker.
 */

(function () {
  "use strict";

  const POLL_INTERVAL_MS = 2000;
  let currentState = "unknown"; // unknown, lobby, in-meeting, left
  let meetingCode = null;

  function extractMeetingCode() {
    const match = window.location.href.match(
      /meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})/
    );
    return match ? match[1] : null;
  }

  function detectMeetingState() {
    // Check if user is in the actual meeting (video tiles present)
    const videoTiles = document.querySelectorAll("[data-participant-id]");
    const endCallBtn = document.querySelector('[aria-label*="Leave call"]') ||
      document.querySelector('[aria-label*="leave"]') ||
      document.querySelector('[data-tooltip*="Leave call"]');

    // Check for "You left the meeting" or rejoin screen
    const leftIndicator = document.querySelector('[data-is-muted]') === null &&
      document.querySelector('[jsname="r4nke"]') !== null;
    const rejoinBtn = document.querySelector('[aria-label*="Rejoin"]') ||
      document.querySelector('[aria-label*="rejoin"]');

    // Check for lobby / "Ready to join?" screen
    const joinBtn = document.querySelector('[aria-label*="Join now"]') ||
      document.querySelector('[aria-label*="Ask to join"]');

    if (rejoinBtn || (leftIndicator && videoTiles.length === 0)) {
      return "left";
    }
    if (endCallBtn || videoTiles.length > 0) {
      return "in-meeting";
    }
    if (joinBtn) {
      return "lobby";
    }
    return "unknown";
  }

  function notifyBackground(type) {
    const url = `https://meet.google.com/${meetingCode}`;
    chrome.runtime.sendMessage({ type, url, meetingCode }, () => {
      if (chrome.runtime.lastError) {
        // Extension context may be invalidated; ignore
      }
    });
  }

  function poll() {
    const code = extractMeetingCode();
    if (!code) return;
    meetingCode = code;

    const newState = detectMeetingState();
    if (newState === currentState) return;

    const prevState = currentState;
    currentState = newState;

    // Transition: entered meeting
    if (newState === "in-meeting" && prevState !== "in-meeting") {
      notifyBackground("MEET_JOINED");
    }

    // Transition: left meeting
    if (newState === "left" && prevState === "in-meeting") {
      notifyBackground("MEET_LEFT");
    }
  }

  // Start polling
  setInterval(poll, POLL_INTERVAL_MS);

  // Also do an immediate check
  poll();

  // Notify on page unload (tab close or navigate away)
  window.addEventListener("beforeunload", () => {
    if (currentState === "in-meeting") {
      notifyBackground("MEET_LEFT");
    }
  });
})();
