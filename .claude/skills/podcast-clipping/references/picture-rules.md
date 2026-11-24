# Picture rules

How each clip should look and move. The kit in `scripts/` plans shots to these rules by default. Your job is to check the result on the contact sheets and override where a shot looks wrong.

## Why this matters

The first cut on the job this skill was built from used one layout for every clip: the host on top, the guest on the bottom, the whole way through. The host:

> "The camera angles aren't used enough. It's just a straight split with me on the top and [the guest] at the bottom, and it should oscillate between the full screen of just me, the full screen of just [the guest] if he's talking, a couple of split screens rather than just staying on the same split screen every time."

> "Make sure throughout these clips you're showing [the guest] as well, even if he's not speaking. Just flicking a clip to him so it's obvious that I'm speaking to him and you can see his face, maybe something of him nodding along."

And when asking for this skill:

> "Using all of the different video channels so that there's movement within the video. For example, it might go 3 to 5 seconds on my face and then 3 to 5 seconds zoomed out from the second camera clip and then another clip of the other guest and then a split screen."

## The shots

A three-camera shoot gives you these. Use all of them in every clip over 20 seconds.

| Shot | Camera | When |
|---|---|---|
| Host close | The host's close camera | The base shot. Opens the clip. |
| Host punched in | The host's close camera, scaled up about 10 to 15% | A change of size on a new sentence or a strong line. |
| Host wide | The wide camera, cropped to the host | The "zoomed out" look. Good on a new thought. |
| Guest speaking | The guest's close camera | Whenever the guest talks for about a second or more. |
| Guest listening | The guest's close camera, the host's voice carries on | 1.5 to 2.5 seconds. Shows the host is talking to someone. |
| Split screen | Host on top, guest on the bottom | 3 to 5 seconds, a couple per clip, at moments of interaction. |

### If the cameras are different

The table is the set-up the kit was built on: a close camera on each person and a wide. Other shoots will differ. Work out the shots from what there is:

- **Every camera that shows the host alone** gives a host shot, plus a punched-in version of it.
- **Every camera that shows the other person alone** gives their speaking shot and their listening shot.
- **Any camera that shows both** gives a wide, and can be cropped to each person for extra shots.
- **No wide camera:** make the "zoomed out" look by using the loosest crop of the host's close camera, and lean more on splits.
- **Four or more cameras:** the kit's planner uses one wide and one close camera per person. Pick the best close camera for each person and leave the rest out, or bring an extra angle in with a hand-written shot list.
- **Two or more other people:** the kit plans for two people only. Treat the one the host is answering as the other person for that clip, and write the shot list by hand where a third person needs to be seen.

The rule underneath does not change: the picture keeps moving, and the viewer keeps seeing who the host is talking to.

A sequence that looks right for a 35 second clip:

Host close 3.5 s. Guest listening 2 s. Host wide 4 s. Host close 4.5 s. Split 4 s. Host punched in 4 s. Guest listening 2 s. Host wide 3.5 s. Host close to the end.

Do not repeat the same three-shot loop. Vary the order.

## Timings

- **Change the picture every 3 to 5 seconds.** A strong line can hold a little longer. Never past 6.
- **No shot under 1.5 seconds.** Shorter reads as a glitch.
- **First shot:** host close, full screen, 3 to 4.5 seconds. Never a split.
- **First sight of the guest:** between 3 and 5 seconds in. The host asked for it inside the first 5 seconds, "but not so fast it is nauseating".
- **Guest on screen at least every 10 to 12 seconds**, and at least twice in any clip over 20 seconds. A clip of 15 to 20 seconds gets at least one.
- **Last 1.5 seconds:** host full screen, unless the guest has the last word.
- **No listening shot during the last sentence.** The ending belongs to the host's face.
- **Put picture changes on sentence starts and joins.** A cut in the picture hides a cut in the sound. A join inside one continuous shot shows as a jump.

## Listening shots

These are what make it feel like a conversation. They are also the easiest shot to get wrong.

- Use the real synced moment. The guest's mouth is shut and they are looking at the host.
- Prefer a visible reaction: a nod, a smile, a laugh, raised eyebrows. Find these around the guest's small words in the transcript ("yeah", "mm-hmm", "100%") and where the picture around their face moves.
- **Reject** any moment where they look away, blink slowly, have eyes shut mid-laugh, drink, check a phone, or have a hand over the face.
- Look at the frames. The automatic checks miss things and flag false problems. On the first job three openings were picked by hand:
  - Clip 02: the guest was clean only until 4.42 s, then their eyes shut laughing. The shot was ended there.
  - Clip 04: eyes squeezed shut for a tenth of a second at the start of a laugh. The shot was started just after.
  - Clip 08d: the guest blinked through 3.0 to 3.8 s. The shot was moved to 3.84 s.
- If there is no clean listening moment near where one is needed, use a split or the wide instead. A bad reaction shot is worse than none.

## Split screens

- Host on top, guest on the bottom.
- Use at moments of interaction: crosstalk, the guest laughing or reacting out loud, a quick back and forth, the host saying "you" to them.
- A couple per clip. Never the whole clip.
- **The caption line sits at y 1408 to 1472.** Frame the bottom half so the guest's eyes and mouth are above it. Move the crop up or scale the face, then check on a frame.

## Framing

- Output is 1080x1920. Each source shot is cropped from a 16:9 frame, so every shot needs its own crop.
- Re-centre the face in every shot. People shift in their chairs over an hour.
- Keep eyes in the upper third. Leave headroom on the wide.
- Match colour between cameras. On the first job the host's close camera ran warmer than the others and was pulled down to match (`colour` in `shoot.json`). Compare skin tone across a cut on the contact sheet.
- Check lip sync on every camera after syncing, before cutting anything. The kit has a check for it.

## The opening

**Default: open close on the host's face, no title on screen.** This is the version the host approved on the first job.

What was tried:

- Round 2: close-up opening with a title hook at chest height. The host called the title position "really weird".
- Round 3: wide opening with the title above the head. Fine, but joining segments inside a wide shot showed small jump cuts on four clips.
- Final: the close-up opening with captions and no title. Approved.

If the user asks for a different opening, add it as another view on the preview page.

## Title hooks

Titles are added after the clips are approved: black text on a white box, just below the host's chin on the close-up opening, above the captions. Everything about them is in `title-hooks.md`.

The close-up opening is what makes that position work: the face fills the top half and the space under the chin is clear. Keep that in mind when framing the first shot. Leave that band free of the microphone where the camera angle allows.

## Older title looks

Two earlier title positions were tried and not kept: a title at chest height (round two, which the host called "a really weird position"), and a title above the head on a wide opening shot (round three). The kit's `--title` option can draw both. Before using it, read `title-hooks.md`, which says where the title goes and how to check it.

## One camera, or one finished video file

Only the first case below has been tried, once, as a test using the wide camera of a three-camera shoot. None has been used on a real job. Treat what follows as the starting point, check the first clip hard, and tell the user the clips came from one source so they know why they move less.

**One camera on a two-shot (both people in frame):**

- Crop each person separately to get a "host" shot and an "other person" shot.
- The kit cuts between those crops as each person speaks, with punch-ins for movement. It does not make listening shots or splits from one camera. Add them with a hand-written shot list if a clip needs them.
- A crop from a wide is soft. From a 4K wide it is about 810 pixels across, which holds up. From a 1080p file it does not, so render from the 4K source.

**One camera on the host only:**

- Make the movement from framing: close crop, tighter punch-in, looser crop.
- There is no picture of the other person. Do not fake one. Choose moments where the host is plainly talking to camera or telling a story.

**A video call recording (Zoom, Riverside, a finished episode file):**

- Find out what the picture is first. Side by side, speaker view that switches, or separate files per person. Ask the show for separate files per person if they exist. Riverside and Zoom can both give them, and they are far better to cut from.
- Side by side: crop each half to get each person. Crop tight enough to lose name tags, borders and the small corner window.
- Speaker view: the picture already switches. You can only cut between what it shows. Use punch-ins for movement and accept fewer listening shots.
- Skip any stretch where a screen is being shared, unless the screen is the point.
- **Check sharpness before promising anything.** A 9:16 crop of one person from a 1280x720 call is about 400 pixels wide, blown up more than two and a half times. That looks soft. If the crop of a face is under about 540 pixels wide, show the user one test clip first and say plainly that the source is low quality.
- Sound is usually one mixed file. Choose moments without both people talking at once.

Hold the same rules as always: the hook, one point, the ending, no dead space, captions, music.

## What to look at before delivering

One contact sheet per clip, made from the captioned video: the first frame, the frame at 1.5 seconds, one frame per shot, and the last frame.

- Does the first frame look like a strong still?
- Any shot where a face is cut off, off centre, or under the captions?
- Any listening shot with eyes shut or looking away?
- Does the colour jump between cameras?
- Count the guest's appearances and the longest stretch without them.
