# 02 - Highlights (run-time template for the local LLM)

Placeholders: `{{call_id}}`, `{{max_highlights}}`, `{{min_seconds}}`, `{{max_seconds}}`, `{{focus}}`, `{{transcript}}`

---

You are given the transcript of a private voice call between "me" and "them". Each line has the form:

`[mm:ss-mm:ss] speaker (lang): text`

The transcript is machine-made and may contain errors, especially in Bengali (`bn`).

Pick the most important or interesting parts of the call: the passages someone would want to hear again or turn into a short video. Good candidates are a complete story, a clear explanation, a decision, a funny exchange, a strong opinion, or an emotional moment. Skip greetings, connection problems ("can you hear me"), small talk and repetition.

{{focus}}

Rules:

- At most {{max_highlights}} highlights.
- Each highlight is one continuous time range between {{min_seconds}} and {{max_seconds}} seconds long, starting where the thought begins and ending where it ends, so it makes sense on its own.
- Start and end times must be times that appear in the transcript.
- Highlights must not overlap.
- Use only what is in the transcript.

Return only JSON, no other text, in this shape:

```json
{
  "call_id": "{{call_id}}",
  "highlights": [
    {
      "start": "mm:ss",
      "end": "mm:ss",
      "title": "short title in English",
      "kind": "story | explanation | decision | humor | opinion | emotion | other",
      "languages": ["bn", "en"],
      "reason": "one sentence on why this part matters",
      "score": 1
    }
  ]
}
```

`score` is a whole number from 1 (mildly interesting) to 5 (the best part of the call). Order the list by start time.

Transcript:
{{transcript}}
