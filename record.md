# Mic Recorder + Live Transcription Feasibility (April 2026)

## Difficulty Summary
Short answer: medium difficulty for a useful MVP, hard for a polished real-time experience.

Given the current app (file upload + backend chunking + whisper inference), adding a mic recorder with live-growing transcript is feasible, but it requires new frontend and backend flow.

## MVP Complexity Breakdown
1. Frontend recorder UI (right side of picker): easy
2. Browser mic capture + periodic chunk upload (every 2-4s): medium
3. Backend rolling-chunk endpoints for partial transcript: medium
4. Stitching and dedup across chunks: medium-hard
5. Smooth low-latency UX with fewer seam artifacts: hard

## Effort Estimate
1. Basic recorder + near-live partial transcript (chunked, not token-streaming): ~2-4 dev days
2. Production-quality live UX (pause/resume robustness, better seam handling, reconnection): ~1-2 weeks

## Recommended Low-Risk Approach
1. Add a Record panel to the right of the existing file picker UI
2. Use MediaRecorder in browser to send chunks every ~3s
3. Add backend session endpoints:
   - start session
   - push chunk
   - read updated transcript
   - stop/finalize session
4. Reuse overlap-aware stitching server-side
5. Display live-growing transcript in existing transcript output area

## What Makes It Hard
1. whisper-server is request/response, not true token streaming
2. Chunk seam artifacts are more visible in live mic mode
3. Browser mic codecs vary (webm/opus/wav), so normalization per chunk is required
4. Latency tradeoff: smaller chunks feel faster but hurt quality/stability

## Practical Recommendation
1. Ship MVP with 3s chunk cadence + overlap-aware stitching
2. Keep explicit "live preview" and "final transcript" behavior on stop
3. Add silence-aware boundary alignment in next iteration for quality

## Suggested Next Step
Draft exact API contract and UI state machine first (Start/Pause/Stop + error states + partial/final events), then implement.
