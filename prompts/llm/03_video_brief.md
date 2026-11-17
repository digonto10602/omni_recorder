# 03 - Video brief (run-time template for the local LLM)

Placeholders: `{{call_id}}`, `{{highlight_title}}`, `{{start}}`, `{{end}}`, `{{style}}`, `{{characters}}`, `{{segment_transcript}}`

A video brief is a scene-by-scene plan that a separate video-making AI model can follow: what is said, and what should be on screen, frame by frame.

---

You are given one highlight from a private voice call: its transcript lines in the form `[mm:ss-mm:ss] speaker (lang): text`. The call is audio only, so nothing is known about what anything looked like. The transcript is machine-made and may contain errors.

Turn this highlight into a video brief.

Visual style requested: {{style}}

Characters: {{characters}}
If no character description is given, call the speakers "Speaker A" (me) and "Speaker B" (them) and describe them only as neutral, non-specific figures. Do not invent the real appearance, age, clothing or location of the real speakers.

Rules:

- Stay faithful to what was said. Dialogue and narration come from the transcript; you may shorten, but do not change the meaning or add events.
- Keep each spoken line in its original language and script, and add an English translation.
- When the speakers describe something (a place, an event, an object), the frames may illustrate that description. Mark such frames `"basis": "described"`. Frames that are your own visual suggestion with no basis in the words are marked `"basis": "suggested"`.
- Each frame description must stand on its own as a prompt for an image or video model: subject, action, setting, camera angle and distance, lighting, mood. Two to four sentences. No references like "same as before".
- Three to eight scenes; each scene two to five frames.

Return only JSON, no other text, in this shape:

```json
{
  "call_id": "{{call_id}}",
  "title": "{{highlight_title}}",
  "source_range": {"start": "{{start}}", "end": "{{end}}"},
  "logline": "one sentence saying what this video is about",
  "style": "{{style}}",
  "scenes": [
    {
      "scene": 1,
      "source_start": "mm:ss",
      "source_end": "mm:ss",
      "summary": "one sentence",
      "lines": [
        {"speaker": "Speaker A", "lang": "bn", "text": "original line", "english": "translation"}
      ],
      "frames": [
        {
          "frame": 1,
          "seconds": 4,
          "basis": "described | suggested",
          "visual": "self-contained description for the video model",
          "on_screen_text": ""
        }
      ]
    }
  ]
}
```

Highlight transcript:
{{segment_transcript}}
