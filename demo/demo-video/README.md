# Live A2A Harness demo video

This directory contains local recording output only. The recorder drives the public
Harness deployment and records the CIP pump mechanical-seal-kit review. It does not
submit human approval or make a business write.

Run from the repository root:

```bash
python3 demo/scripts/record_live_a2a_demo.py
```

The result is `demo/demo-video/live-a2a-harness-demo-v2.mp4`: a 1920×1080
H.264/AAC video with English titles, enlarged evidence text and a dedicated caption
footer. Selected scenes play at normal speed; waits and positioning between scenes
are cut. The previous video is retained for comparison.

Scenes cover the Guide, request, verified Grounding, initial RPT, Team handoff,
actual tool input/output, Specialist and Team reviews, final answer, next action,
and final RPT. Transitions use real SSE events and actual result elements.

Use `--headed` to watch Chromium or `--attempts 1` for a single attempt. Two
attempts are allowed by default; three is the maximum. Raw WebM, scene screenshots,
timing metadata and failed diagnostics remain under `attempts/`.
`latest-run-v2.json` records the successful run and media checks.

Requirements: Python 3 with Playwright and Chromium installed, plus `ffmpeg` and
`ffprobe` on `PATH`.

## Full conversation with speech bubbles

```bash
python3 demo/scripts/record_full_a2a_conversation.py
```

This produces `live-a2a-harness-full-conversation.mp4`. It records a fresh real
run, then films every original UI message in chronological order at reading speed.
All Team handoffs, Specialist replies, Team syntheses, Orchestrator observations,
and final responses are included. Review and tool-result details are expanded;
long messages are scrolled through with overlapping views. The walkthrough is one
continuous take, with no message cuts or speed-up and no one-minute duration limit.

English explanations appear in a separate speech bubble with a tail pointing to
the current message. The annotation is explicitly labeled Conversation Guide and
does not replace any original Agent text. Green highlight boxes and footer captions
are not used. The initial server-processing wait precedes the walkthrough and is
excluded; the resulting video is a full walkthrough of a recorded live run.

The original WebM, every viewport screenshot, and `conversation.json` coverage
log remain under `attempts/`. `latest-full-conversation.json` lists the final
file, message coverage, and media checks. Use `--min-hold 6` for longer minimum
reading time, or `--attempts 1` for a single live run.

## Live streaming with faster loading

For the natural live pace without any reading pauses, use the newer recorder:

```bash
python3 demo/scripts/record_realtime_a2a_demo.py
```

This produces `live-a2a-harness-realtime.mp4`. The site's real stream is consumed
unchanged, without queued delivery or per-message reading holds. Speech bubbles
follow incoming messages automatically. After 1.5 seconds without a content
change, idle loading plays at 6×; text updates stay at normal speed. The complete
chronology remains in the video, with the original message log retained.
`latest-realtime.json` includes coverage, duration, and the raw WebM location.

The older recorder below adds reading pauses and therefore makes a longer video.
The streaming and realtime encoders now use H.264 CRF 27, the slow preset,
still-image tuning, and 20 fps to keep UI recordings compact at 1080p.

```bash
python3 demo/scripts/record_streaming_a2a_conversation.py
```

This produces `live-a2a-harness-streaming.mp4` at 1920×1080 with H.264/AAC.
It films the real live SSE conversation as responses appear, with English speech
bubbles pointing to the current speaker. Every conversation message is included.
The browser reads the genuine network stream independently and consumes unchanged
packets in order, pausing between responses to read long messages and tool results.
It does not replay a completed transcript, generate response text, or change the
backend task. Network receipt and UI delivery timestamps are saved separately.

Only waiting intervals play at 6×, indicated by a `LOADING · 6×` badge. Responses,
reading pauses, and scrolling through long evidence remain at normal speed; no
intermediate conversation is cut. Raw WebM, page screenshots, SSE trace, coverage,
and the edit timeline are saved under `attempts/`. `latest-streaming.json` links
the latest video, diagnostics, and media checks. Two attempts are allowed by
default; use `--attempts 1` for one attempt or `--headed` to watch the browser.
