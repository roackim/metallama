# Audio Transcription Quality Notes (April 2026)

## Current Situation
Quality is improved with overlap chunking, but residual seam artifacts still appear in long-form transcription, for example:
- "incompr ehensible" style splits
- occasional boundary micro-cuts

This is expected when chunk boundaries are not silence-aware and stitching is mostly time-based.

## Why It Still Happens
1. Boundary micro-cuts
- Even with overlap, a phoneme can start/finish close to the seam and produce split words.

2. Whisper tokenization artifacts
- French accents/apostrophes can appear with odd spacing in low-confidence spans.

3. Merge layer is not linguistic
- Timestamp stitching reduces duplicates and clipping, but does not repair malformed words.

## Recommended Next Steps (Priority Order)
1. Silence-aware chunk boundaries (highest impact)
- Replace fixed hard cuts with cut-near-silence around target boundary.
- This gives the largest quality gain for long audio.

2. Keep overlap, add lexical seam matching
- At each seam, compare suffix/prefix word windows and choose best merge point by token similarity.
- Improves joins beyond strict timestamp thresholds.

3. Add lightweight FR post-correction
- Apply conservative repair for seam-like patterns (e.g., letter-space-letter inside likely words).
- Use dictionary-backed checks to avoid overcorrection.

4. Optional Pro mode refinement
- Keep raw transcript + provide refined transcript (grammar/punctuation/homophone cleanup).
- Use strict prompt: preserve language and meaning, no summarization.

5. Confidence-aware correction
- Apply stronger corrections only near low-confidence or seam regions.
- Reduces risk of changing already-correct text.

## Practical Direction
Best production trajectory:
- Silence-aware chunking + overlap lexical stitcher as base
- Optional LLM refinement as a second pass for readability

This combination gives robust long-audio handling while preserving faithful raw output.
