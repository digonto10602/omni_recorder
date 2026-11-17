# 01 - Call notes (run-time template for the local LLM)

Placeholders: `{{call_id}}`, `{{duration}}`, `{{output_language}}`, `{{transcript}}`

---

You are given the transcript of a private voice call between two people, "me" and "them". Each line has the form:

`[mm:ss-mm:ss] speaker (lang): text`

A Bengali line may be followed by a line starting with `    en:` giving a machine translation of it; treat the Bengali as the original and the translation as a help, and if the two disagree, say the passage is unclear.

`lang` is `bn` (Bengali) or `en` (English). Speakers may switch language or mix English words into Bengali. The transcript was made by a machine and contains mistakes, especially in Bengali; when a word looks wrong, use the surrounding context, and if the meaning is still unclear, say it is unclear instead of guessing.

Write notes in {{output_language}}. Use only what is in the transcript. Do not add facts, names or dates that are not there. After every point give the time range it comes from, like `[04:10-05:02]`.

Produce exactly these sections in Markdown:

## Summary
Three to six sentences on what the call was about.

## Languages
Which languages were spoken, roughly how much of each, and who spoke which.

## Topics
One bullet per topic, in the order discussed, each with one or two sentences and a time range.

## Decisions and plans
What was agreed or planned, who will do it, and by when if stated. Write "None" if there were none.

## Open questions
Things left undecided or unclear.

## Memorable moments
Stories, jokes, strong opinions or emotional moments worth revisiting. For each, one line of description, the time range, and one short direct quote in its original language and script, followed by an English translation in brackets.

## Unclear passages
Time ranges where the transcript was too garbled to trust.

Call: {{call_id}}  Duration: {{duration}}

Transcript:
{{transcript}}
