"""Paths, reference data and the 50 test sentences for the voice-cloning benchmarks.

Importing this module creates RESULTS_DIR, as the original script did at import time.
"""
from pathlib import Path

# One level deeper than the original script, so go up one more to reach benchmarks/.
BENCH_DIR = Path(__file__).parent.parent.parent
RESULTS_DIR = BENCH_DIR / "results"
GENERATED_DIR = BENCH_DIR / "generated"
VOICE_DATA = Path.home() / ".clipcannon" / "voice_data" / "boris" / "wavs"
REAL_REFERENCE = Path("/home/cabdru/.clipcannon/projects/proj_f0101c2d/audio/chris_real_reference.wav")
REF_TEXT = "OCR Provenance MCP server is the best AI memory system in existence"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 50 novel sentences Chris never said - for generating test clips
TEST_SENTENCES = [
    "The weather outside is absolutely beautiful today.",
    "I just finished reading a really interesting book about space exploration.",
    "Can you believe how fast technology is advancing these days?",
    "Let me show you how this new feature works in the application.",
    "The meeting has been rescheduled to three o'clock tomorrow afternoon.",
    "We need to discuss the quarterly budget before the end of the week.",
    "I think the best approach would be to start with the basics first.",
    "Have you ever tried cooking Italian food from scratch at home?",
    "The traffic on the highway was absolutely terrible this morning.",
    "I'm really excited about the upcoming product launch next month.",
    "Please make sure to save your work before closing the application.",
    "The customer feedback has been overwhelmingly positive so far.",
    "Let's take a quick break and come back in about fifteen minutes.",
    "I noticed a few small issues that we should probably address soon.",
    "The sunset over the mountains was one of the most beautiful things I've ever seen.",
    "Don't forget to update your password at least once every ninety days.",
    "We should consider expanding our team to handle the increased workload.",
    "The presentation went really well and the client seemed very impressed.",
    "I'll send you the report by end of business today at the latest.",
    "Running every morning has completely changed my energy levels throughout the day.",
    "The new restaurant downtown has the best tacos I've ever tasted.",
    "Make sure you double check the numbers before submitting the final report.",
    "I've been working on this project for almost three months now.",
    "The conference call is scheduled for nine thirty eastern time.",
    "We should probably back up all the important files before the migration.",
    "The garden is looking amazing after all the rain we had last week.",
    "I'll pick up some groceries on my way home from the office.",
    "The documentary about ocean life was absolutely fascinating to watch.",
    "Please review the pull request when you get a chance today.",
    "The kids had so much fun at the park yesterday afternoon.",
    "We need a more efficient way to process these incoming requests.",
    "The flight to New York has been delayed by approximately two hours.",
    "I'm thinking about signing up for that online photography course.",
    "The team really pulled together and delivered an amazing result.",
    "Can you send me the link to the shared document we discussed?",
    "The air conditioning in the office needs to be repaired urgently.",
    "I learned so much from attending that workshop last weekend.",
    "The database performance has improved significantly after the optimization.",
    "Let me know if you have any questions about the new process.",
    "The morning fog made the drive to work quite a bit more challenging.",
    "We should celebrate the team's achievement with a dinner this Friday.",
    "The software update includes several important security patches.",
    "I just got back from vacation and I'm feeling completely refreshed.",
    "The quarterly results exceeded our expectations by a significant margin.",
    "Please remember to lock the door when you leave the building tonight.",
    "The podcast episode about artificial intelligence was incredibly thought provoking.",
    "We might need to adjust our timeline based on the latest feedback.",
    "The autumn leaves are changing color and the whole neighborhood looks stunning.",
    "I'm going to reorganize my desk this weekend to be more productive.",
    "The project deadline has been moved up by two weeks unfortunately.",
]
