---
name: podcast-clipping
description: Turn a podcast, interview, talk or long video into finished vertical short-form clips (1080x1920) for the host's channel. Finds the best moments, scripts each clip around one point with a hook and a real ending, cuts between every camera so the picture keeps moving and the other person is seen, removes all dead space, burns in captions, adds quiet background music, builds a preview page for review, then writes title hook options and makes one version per hook the user shortlists. Includes a Python + ffmpeg kit that syncs cameras to microphones, transcribes locally, plans shots, renders and checks every clip. Use when someone asks to clip, cut up or find clips from a podcast, interview or long recording, says they were on a podcast and want clips, or asks for title hooks on clips.
---

# Podcast clipping

Turn one long recording into a batch of short clips the user can post without touching them.

This skill was built from a real job: a 56-minute podcast with three cameras and three microphones. It became 14 approved clips of 21 to 60 seconds. It took three review rounds to get there. Every correction the host made in those rounds is written into this skill, so the next recording should land in one.

Read the whole of this file first. Then read each reference file at the step that names it.

A note on words. **The host** is the person whose channel the clips are for. They may be the host of the show or a guest on someone else's. **The guest** and **the other person** both mean whoever the host is talking to, whichever chair they are in. **The user** is the person asking you for the clips, usually the host.

## What done looks like

- 10 to 15 clips, 20 to 60 seconds each. Fewer if the recording only supports fewer. Never pad the count with weak clips.
- Each clip makes one point, opens on a hook in the host's own voice, and ends on a line that lands.
- 1080x1920. Opens close on the host's face. The picture changes every 3 to 5 seconds across every camera. The other person is first seen between 3 and 5 seconds in, and regularly after.
- No dead space anywhere. No clipped words.
- Captions on every clip.
- The base clips carry no title. Title hooks come after approval, as extra versions: one finished file per hook the user shortlists.
- Quiet background music, audible from the first second.
- One preview page where the user can tap through every clip.
- The approved set filed where the user wants it, with a `With music (final)` folder, a `Without music` folder, and a `With title hook` folder once the hooks are on.

The original brief, in the host's words: "being able to take another podcast... find the best moments, order the clips in a way where there's a coherent throughline and message in the short clip."

## First run: check the setup

**Before anything else, the first time this skill runs, read `references/first-run-setup.md` and run its check.** Many users will have opened Claude for the first time today. Show them one plain checklist of what is ready and what is missing, why each thing is needed, and walk them through fixing each missing item one step at a time. Check each item yourself before ticking it.

What it checks:

- **A Mac with Claude Code.** The cutting runs on their computer.
- **The clipping tools** in `scripts/` (`bash scripts/setup.sh`: Python 3.10+, ffmpeg and three small models, about 1 GB, no GPU).
- **The Instagram Edits app, connected to Claude.** Edits adds the music and the title hooks with Instagram's own licensed songs and fonts. Claude drives it through the Edits automation server (usually named `metapilot-native`).
- **A caption font file.** Any bold sans .ttf or .otf they have the right to use. None is bundled. See `references/captions.md`.
- **Where to save the finished clips.** Ask: "Where do you want the finished clips saved? Do you have a content folder in Google Drive, Dropbox or OneDrive? Or I can save them in a folder on this Mac."
- **Disk space.** A few GB per hour of footage.

The footage itself is best as each camera and each microphone in its own file. One finished video file also works, with less movement in the picture (see step 1).

If something can't be set up (no Mac, no Edits, no Claude Code), `first-run-setup.md` says what still works. Say it in one line and carry on.

## How to run it

If your agent can run subagents, use them. The main thread orchestrates and talks to the user. Hands-on work goes to subagents with a narrow brief and the exact files to read. Check what comes back before it goes anywhere near the user.

Jobs that split cleanly:

- Sync and transcribe (one agent).
- Find moments (two agents working independently on the same transcript, so their lists can be compared).
- Cut and render (one agent with the script kit).
- Check the finished clips (a fresh agent that did not cut them).

Decisions about which moments make the list, how each script runs and what the user sees stay with the main thread. Without subagents, do the same steps in order yourself, and do the check step as if you had not cut the clips.

The user's request to clip the recording covers every step inside it: downloading their footage, rendering, adding music, copying the finished files to the folder they named. Do not ask them to confirm those. Do ask before deleting anything they have not asked you to remove, and never post or send anything on their behalf.

## Before you start

Find out, from the request or by looking, rather than by asking:

- **Where the footage is.** Wherever it lives: a local folder, Google Drive, Dropbox, a link from the show. If it is a share link, download it into the job folder.
- **Where finished clips go.** If the user has not said, ask once: "Where do you want the finished clips saved? Do you have a content folder in Google Drive, Dropbox or OneDrive? Or I can save them in a folder on this Mac." Save into that app's folder on their computer so it syncs. Inside it, use `Clips/YYYY/SOURCE NAME/` with the three folders above. See `references/delivery.md`.
- **The caption font.** Ask for the file if none is in the job folder, or use a font already on the machine that they are happy with.
- **Their songs for music.** Use their bank if they have one. If not, ask for three to five songs they like under talking clips, or deliver without music first and say so.
- **What the channel is about**, so the moments you pick are in its lane. Read their channel or ask in one line.

If you do need to ask, put every question in one short message, then start on the footage while you wait.

## The rules

Each one came from something the host said about the first batch.

1. **Clips are for the host's channel.** The host talking, or the host answering. Moments where the guest is the main speaker are noted in a list for the guest and not cut.
2. **Open on a hook.** The host's own strongest line, which may be lifted from later in the answer. A question the other person asks is not a hook, because the viewer is not the one holding it.
3. **One point, with its context, and a real ending.** Clips that stopped abruptly got "what was the point of that video?" If the ending is not tangible, keep going into the example.
4. **The angle stays congruent.** A strong first line followed by a story with a different feel got the whole clip rejected. Follow what the host actually said next.
5. **No dead space, and never a clipped word.** A clip starts as the first word starts. It ends on the frame the last word ends. Pauses inside are cut to 0.10 to 0.15 seconds.
6. **Use every camera so the picture moves.** In the host's words: "3 to 5 seconds on my face, then 3 to 5 seconds zoomed out from the second camera, then another clip of the other guest, then a split screen." Never one layout for a whole clip.
7. **Show the other person even when only the host is speaking.** Flick to them listening or nodding so it is obvious the host is talking to someone. First time between 3 and 5 seconds in. Earlier than that felt jumpy.
8. **Captions on every clip**, in one consistent style.
9. **Music from the first second.** Most songs open quietly, so start the song past its intro.
10. **Never name the studio or venue where it was recorded**, in a clip's text or in anything written about the clips, unless the user asks.
11. **Review happens on a preview page.** Video files attached in a chat are slow to load.
12. **When the user likes a clip, leave it alone.** Change only what they name. When they love one, offer more hooks for it.
13. **Title hooks break by phrase.** "why you need to be / in the right room", never "why you need / to be in the right room". Black text on white, below the face and above the captions.

## Workflow

### 1. Take the job in

- Find the files. Note every camera file and every audio file, with durations.
- **Whose microphone is whose:** transcribe the first two or three minutes of each audio file (`transcribe.py --peek 150` in the kit). The file where the host's words are loud and clean is theirs. Introductions usually settle it ("thanks for having me", names). Do not go by file names.
- **Which camera is which:** pull one frame from each camera at the same moment. You will see a close shot of each person, a wide, or both people together. The kit works out who is on which camera by matching mouth movement to each microphone. Read what it decided and correct it if it is wrong. Do not guess from looks.
- **Note what you have to work with:**
  - Several cameras and one microphone each: the full method.
  - Several cameras and one mixed sound file: the kit cannot tell who is speaking, so it will not cut to the other person by itself. Place their shots by hand, or ask the show for separate microphone files.
  - One camera or one finished video file: the reduced method in `references/picture-rules.md`.
  - More than one other person: treat the one the host is answering as "the other person" for that clip, and use shots of the rest only when they speak or visibly react.
- Tell the user in one line what you are starting on. Do not ask them questions you can answer from the footage.

### 2. Set up, sync and transcribe

Follow `scripts/README.md` for the commands. One naming point: the kit calls the host `host` and the other person `guest`, whoever's show it is. In short:

- Run `bash scripts/setup.sh` once per machine.
- Make a job folder and write its `shoot.json` (cameras, microphones, people, caption font). `scripts/examples/shoot.json` is a filled-in example.
- Work from 1080p copies of the cameras (proxies). If the footage only comes at 4K, the kit makes its own 1080p copies once. Keep the full-size files for the final render.
- Sync every camera to the audio timeline (`ingest.py`). That timeline is the master clock for everything after.
- Transcribe each microphone to word timings (`transcribe.py`). This runs locally, about 10 minutes per microphone-hour on 4 CPUs. You get a readable transcript with speaker names and timestamps.

### 3. Find the moments

Read `references/finding-and-scripting-clips.md`.

Two agents (or two separate passes) read the full transcript independently and each return a list. Merge the lists yourself:

- A moment both found goes to the top.
- A moment only one found stays if you can write its point in one sentence and name its first line and its last line. If you cannot, drop it.
- If two moments make the same point, keep the one with the stronger first line.
- Stop when the next moment would not get past the rejection list in the reference file. Ten strong clips beat fifteen mixed ones.

Do not send the user the shortlist and wait. Cut the clips and show them finished work. People review clips, not lists.

Also keep the list of moments where the guest is the main speaker. The user may pass it to them.

### 4. Script each clip

Same reference file. A script is an ordered list of segments from the recording, written into `clips/clips.json` (see `scripts/examples/clips.json`). For each clip write:

- The hook line it opens on, and why a viewer keeps watching.
- The segments in play order, with a note of the words that should be heard at each join.
- The ending line, and what it lands.
- Anything the user should check: a number that belongs to the guest, an admission, two moments joined from far apart.

Read every script aloud in your head as a stranger would hear it. If context is missing, add the segment that supplies it. If it wanders, cut.

### 5. Cut the picture and the sound

Read `references/picture-rules.md` and `references/audio-and-cutting.md`.

Render fast previews first (`render.py --preview`). Look at the contact sheets and the heard-words check for every clip. Fix, then render full quality (`render.py --final`).

### 6. Captions

Read `references/captions.md`. The kit writes each clip's caption text to its own file, then burns it in. Fix the words by hand against a full transcription of the finished clip, then re-run only the caption pass.

There are two outputs per clip: a clean cut with no text, and the captioned clip. Text changes then never need a re-cut.

### 7. Check every clip before the user sees it

A contact sheet is one image with a row of frames from the clip: the first frame, one per shot, and the last. A fresh agent looks at the contact sheets and reads the checks (`check.py`). Every clip must pass all of these:

- First word and last word whole. Nothing after the last word.
- Every join sounds like one thought. No doubled word, no double breath.
- Captions match what is said. No dropped small words, no stutters.
- No shot under 1.5 seconds. Other person first on screen between 3 and 5 seconds in, and at least every 10 to 12 seconds after.
- Listening shots: eyes open, looking at the host, no hand over the face, not drinking or checking a phone.
- In split screens, no face under the captions.
- Lips and voice line up on every camera, within one frame.
- The script still makes sense heard cold. Say so plainly if a join does not.

Fix and re-check. If a clip still fails one item after two attempts, do not hold the batch. Deliver it with a one-line note saying exactly what is wrong, or leave it out if the fault is a clipped word.

### 8. Music

Read `references/music.md`. Pick each clip's song by what the clip is doing. Start it past its intro. Add it in Edits (the default, with Instagram's licensed songs), or mix it in with the ffmpeg command in that file if there is no Edits. Measure it with `music_check.py`.

Do this before the first delivery. Redoing the music on a recut clip takes about a minute. If music can't be added yet, deliver without it and say so.

### 9. Show the user

Read `references/delivery.md`. Build the preview page (`preview_page.py`) with two views: with music, and without. Name the song under each clip.

Send one message: where the page is, where the full quality files are, and anything to listen for. Keep it short, with short lines and white space.

### 10. Revision rounds

- Treat each note as about that clip only, unless the user says otherwise.
- Quote their words into the brief for whoever recuts it.
- Give a recut clip a new id (03 becomes 03b) and keep the old one until they approve.
- If a note needs a line said somewhere else in the recording, find it in the transcript, tell them which lines you are joining, then cut. Do not wait for a reply.
- If they ask for a different opening, make it as an extra view on the preview page. Do not replace the version they have already seen.

### 11. File the approved set

When the user says the clips are good:

- Put the final set in `With music (final)` and the no-music copies in `Without music`, in the folder they named. List the folder and count the files.
- Remove superseded versions only when they ask. Prefer a trash that can be undone. Say what was removed.
- Note where the approved set lives and the preview page, wherever you keep project notes.
- A new rule they gave about clipping belongs in this skill. Propose it under "Improving this skill" below.

### 12. Title hooks

Read `references/title-hooks.md`. This round starts once the clips are approved, because the hooks are written from the finished cuts.

- Write ten options per clip from a transcript of each finished clip. Use a hook-writing skill if you have one. Put them in one document with a heading per clip, a numbered list, and two starred picks.
- Send the document and wait for their shortlist. This is one of the few points where the work waits on the user. They answer with numbers and may add lines of their own.
- Put every shortlisted hook on its clip: in Edits (the default, with Instagram's own Classic font), or burned in with the kit. One finished version per hook. Break each hook by phrase.
- Look at a still of every version (`title_check.py` helps). Copy them into `With title hook`. Send one page of stills.

## What the script kit has and has not been proven on

Be straight with the user about this when a recording is different from the first one.

- **Proven:** three cameras (a wide and a close camera on each person), one microphone each, 23.976 frames a second, 4K sources with 1080p proxies, English. Two clips re-made with the kit matched the hand-approved files: same length to the frame, same cuts, same shots, same captions, identical sound.
- **Tried once:** one wide camera showing both people, with two microphones. It cuts between crops of each side. No listening shots or splits.
- **Built in but never run:** two close cameras with no wide. A wide and one close camera.
- **Not built:** more than two people. More than one close camera per person (pick the best one). One mixed sound file with speakers told apart (with one track, every word is treated as the host's, so the other person is never cut to automatically). Languages other than English (the speech recogniser is English only). Landscape output.
- **Never run:** a video call recording. Any frame rate other than 23.976.

When a job falls outside the proven set-up, do one clip end to end first and check it hard before doing the batch. Hand-written shot lists (see `scripts/README.md`, "Overriding a shot by hand") cover what the automatic planner cannot.

## Reference files

- `references/first-run-setup.md`: the first-run checklist, in plain words, with the fix steps for each missing item (Edits, its connection to Claude, the toolkit, the font, where to save).
- `references/finding-and-scripting-clips.md`: what makes a moment worth cutting, what gets rejected, how to script, and every script correction from the first job.
- `references/picture-rules.md`: the shot vocabulary, timings, listening shots, split screens and openings.
- `references/audio-and-cutting.md`: clean edges and joins, microphone handling, loudness, and the checks.
- `references/captions.md`: the caption spec, chunking, text fixes and the font.
- `references/music.md`: keeping a song bank, which song suits which clip, where each song should start, levels, adding it, and checking it.
- `references/delivery.md`: the preview page, where files go, and what happens after approval.
- `references/title-hooks.md`: writing the options, what tends to get picked, the look and position, how to break the lines, and putting them on the clips.
- `scripts/README.md`: the script kit, command by command. `scripts/examples/` holds a small anonymised example of each settings file.

## When something is missing

- **Footage behind a share link** (Dropbox, Drive, WeTransfer, Frame.io): download it into the job folder. If the link needs a login you do not have, ask the user to download it or share it differently.
- **The show sends one finished video, not camera files:** use the reduced method. Tell the user the clips will move less, and that separate camera and microphone files would give better clips if the show can send them.
- **One camera only:** cut with framing changes instead of camera changes, and say so in the delivery message.
- **No caption font yet:** render previews with the stand-in font (`CLIPKIT_FONT_FALLBACK=1`), say the captions are drafts, and re-run the caption pass when the font arrives. It takes seconds.
- **No music yet:** deliver without music, say so, and add it when the songs arrive.
- **A song is not available in the user's editor:** pick the next best fit from the bank and tell them which one you swapped.
- **A cloud drive returns errors:** make one call at a time, and check whether a write landed before retrying.

## Improving this skill

At the end of a run, review it briefly:

- Did any step fail, need a workaround, or behave differently than this file describes?
- Did the user correct, reject, or rework something this skill produced?
- Did you discover something a future run needs (a tool quirk, a new song, a better sequence)?

Propose a change only if it would change what a future run does, or prevent a repeat of a real mistake. Most runs should end with nothing to propose. If something clears that bar, end with one line: **Proposed update to this skill:** what changes and why. Change the skill only after the user approves.
