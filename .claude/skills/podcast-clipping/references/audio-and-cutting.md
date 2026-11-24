# Audio and cutting

Where every cut goes, and how to prove it is clean. On the job this skill was built from, this is what the host noticed most.

## What the host said

> "It says 'that was good cop, that was good copy'. It cuts me off a little bit too early."

> "It's almost perfect. Just QA it and make sure that it flows a little bit better."

> "Cutting out pauses and any dead space."

And from a review of other short videos the same week, which applies here too: still too much tail. Cut on the frame the last word ends, or one to two frames before it. No trailing silence at all.

## The standard

- **Start:** the clip begins as the first word begins. About two frames before, never after.
- **End:** the clip ends on the frame the last word ends, or one to two frames earlier. Nothing after it. No breath, no next word.
- **Inside:** pauses of about 0.25 seconds or more are cut down to 0.10 to 0.15 seconds. This applies mid-phrase too.
- **Joins between segments:** sound like one thought. Similar level, 0.10 to 0.15 seconds of air, no double breath.
- **Never clip a word.** A shaved first consonant or a missing last syllable is worse than a frame of silence.

## Why the obvious methods fail

These were learned the slow way. Do not repeat them.

- **Speech recogniser word times are not cut points.** The last word's end time ran up to half a second late. First words came back late too, so quiet openers ("I", "And", "So", "It's") were shaved.
- **A fixed loudness threshold is fooled** by breaths, room hiss and the other person's microphone.
- **Recognising a whole clip at once misreads the edges.** "That" became "Now there". Use the whole-clip pass only to catch dropped words in the middle.
- **Recognising only the last 1.5 seconds misreads endings.** Use a 3 second window for the end.

## The method that works

The kit does this. Know the steps so you can tell when it has gone wrong.

1. **Find speech regions** with a voice activity detector (Silero, speech probability 0.7 or more) on the speaker's own microphone.
2. **Refine each edge** using energy in the speech bands, measured against that file's loud speech and its own noise floor. Keep the release of a final t, d, k or p (within 0.15 seconds of the word).
3. **Starts:** take the earlier of the refined edge and the transcript word start minus 0.04 seconds.
4. **Ends:** take the last strong frame of the final word, floor it to a frame, then take one more frame off. Check that the next word in the source, often 0 to 80 milliseconds later, is not heard.
5. **Confirm every edge by listening with the recogniser.** Recognise a short window at the start and a 3 second window at the end. If the first or last word is missing, step the edge out one frame at a time, three frames at most, never past where a neighbouring word begins.
6. **Cut the pauses inside** and close each gap to 0.10 to 0.15 seconds.
7. **Snap every cut to a frame** of the output. Keep the source frame rate. It was 23.976 frames a second on the first job. Another show may be 25 or 30.

## Microphones

With one microphone per person:

- Use the host's microphone for the host and the guest's for the guest.
- While one person talks alone, duck the other microphone. Otherwise bleed and overlapping "yeah"s smear the words.
- Where both are meant to be heard (crosstalk, a laugh, a reaction you want), keep both. Say so in the segment note.

With one mixed track, skip the ducking and be stricter about choosing moments without crosstalk.

Work out which microphone is whose from the transcript, not from the file name.

## False starts and repeats

Handle them exactly as the segment note says. Typical cases:

- A doubled word ("you you"): keep one.
- A restarted phrase ("st... SOP"): keep the clean take.
- A phrase said twice with a restart: keep the last complete, clearly voiced take.

Then make sure the caption text matches what was kept.

## Loudness

- About -15 LUFS integrated. LUFS is the standard measure of how loud something sounds overall. Instagram, TikTok and Shorts all play at around this level.
- True peak under -1.5 dBTP, so the loudest instant never distorts.
- Both voices at a similar level. The guest's microphone is often quieter.
- This is the level of the clip before music. Music sits well under it (see `music.md`).

## The heard-words check

For every clip, after the audio is rendered:

1. Recognise the whole clip.
2. Recognise a window one second either side of every join.
3. Recognise the first 1.5 seconds and the last 3 seconds.
4. Compare all of it with the words the script intends.

Write the result to a text file next to the clip, with the join windows listed separately. Fix anything that differs for a reason other than the recogniser's spelling.

Things this check caught on the first job:

- "that was good cop" (last word shaved at a join).
- Quiet first words missing at the start of segments.
- A doubled word left in at a join.
- The first syllable of the next sentence left on the end of a clip.

## Sync

- One audio timeline is the master clock. Every camera gets an offset to it.
- Find each offset by matching the camera's own sound against the master audio. Then check it by eye: the kit's lip sync check compares mouth movement with the voice.
- Offsets on the first job, as an example of scale: 21.5, 45.8 and 124.0 seconds. Cameras start at different times, so never assume zero.
- Long recordings can drift. Check sync near the start and near the end of the recording.

## Sources

- Work from 1080p copies of each camera (proxies) and the audio files. Cut previews from these. If you only have the full-size files, the kit makes its own 1080p copies once.
- You do not need to download huge 4K originals if your storage gives direct download links (the first job's were 25 GB each). For the full quality pass, the kit can read them from a link, seeking to the part it needs. Put the link in a `.url` file (see `scripts/README.md`). Otherwise point it at local files.
- Signed download links usually expire (often after a day). Refresh them before a long render.
- Never paste a signed link into a message, a note or the skill.

## If the machine restarts mid-job

Background renders stop. Files already written survive. Restart clip by clip, skipping the ones that finished (`render.py --skip-done`).
