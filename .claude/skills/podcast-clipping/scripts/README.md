# Podcast clipping kit (scripts)

Turns a two-person podcast shoot into vertical 1080x1920 clips.
It syncs the cameras to the mics, transcribes, plans the shots,
renders, burns captions, checks the result, and builds a review page.

It was built on a real 56-minute episode (3 cameras, 2 mics).
A small, anonymised example of each settings file is in `examples/`.

## Contents

1. Where it runs and what setup installs
2. Names: host and guest
3. The job folder
4. Commands in run order
5. Config formats
6. Which camera and which mic is whose
7. Other camera setups (one camera, two close-ups, four cameras)
8. Overriding a shot by hand
9. Caption font
10. Frame rate
11. Resuming after a restart
12. Measured timings
13. Gotchas
14. Title hook check

## 1. Where it runs and what setup installs

It was built and tested in a Linux container (4 CPUs, 15 GB RAM, Python 3.13).
It should also run on a Mac or any Linux machine with Python 3.10+ and ffmpeg. No GPU is needed. Everything runs on the CPU.

You need `ffmpeg` and `ffprobe` on PATH, with libx264 and the ebur128 filter.
A normal `apt-get install -y ffmpeg` (Linux) or `brew install ffmpeg` (Mac) has both.

```
bash scripts/setup.sh
```

It installs into `~/.cache/clipkit` (change it with `CLIPKIT_HOME`).
Nothing goes inside the kit folder.

- `venv/`: Python packages, pinned:
  numpy 2.5.3, scipy 1.18.1, soundfile 0.14.0, sherpa-onnx 2.0.1,
  onnxruntime 1.29.0, opencv-python-headless 5.0.0.93, pillow 12.3.0.
- `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/`: the recogniser
  (NVIDIA Parakeet TDT 0.6B v2, English, int8, about 480 MB download).
  From the sherpa-onnx GitHub release.
- `models/silero_vad.onnx`: voice activity detector. It cuts the audio into pieces for the recogniser.
- `models/yunet.onnx`: the YuNet face detector (OpenCV model zoo, through GitHub's LFS host).

All downloads are from github.com or githubusercontent.com. huggingface.co is not needed.
The script checks that ffmpeg is there, then that each model loads.
It is safe to run again: finished steps are skipped.

The scripts find the venv on their own.
If you run one with a Python that lacks the packages, it restarts itself under the venv.
To use a different venv or model folder, set `CLIPKIT_PY` or `CLIPKIT_MODELS`.

## 2. Names: host and guest

The kit calls the two people `host` and `guest`.

- **host** = the channel owner whose clips these are.
  This holds even when they are the guest on someone else's show.
  If you go on someone else's podcast, you are still `host` here.
- **guest** = the other person.

Display names go in `shoot.json` `people`.
The clip planner is built around the host: openings, rhythm shots
and the final shot are on the host, and the guest gets
talking shots, listening cutaways and splits.

## 3. The job folder

One folder per episode. Every script takes `--work DIR` (or `CLIPKIT_WORK`).

```
W/
  shoot.json                you write this (section 5)
  manifest.json             ingest.py writes it: sync, roles, crops, colour, mics
  audio/mic_host.wav        mic per role (a link to your file, or extracted)
  audio/mic_guest.wav       (or audio/mic_shared.wav for one mixed track)
  proxies/                  1920x1080 proxies, only when you gave none
  work/                     intermediate files (a16/, sync_result.json, faces.json, tx/ ...)
  transcript/
    words_host.json         [{"w","s","e"}], seconds on the master clock
    words_guest.json
    speech_regions.json     {"host": [[s,e]...], "guest": [...]}
    transcript.md           readable, with speaker turns
  clips/
    clips.json              the clip list (you or the clip finder write it)
    edits.json              hand edits per clip id (optional)
    wide_openings.json      hand overrides for the wide opening (optional)
  out/closeup/              the default style
    clean/<name>.mp4        picture + sound, no captions
    <name>.mp4              captions burned in: the deliverable
    <name>.edl.json         the cut: pieces, shots, words, edge checks, audio stats
    <name>.captions.json    caption lines [{"t0","t1","text"}], output seconds
    <name>.heard.txt        the heard-words diff
    <name>.check.json       loudness, peaks, silences, clicks, sync per shot
    <name>_sheet.jpg        contact sheet
    titled/<name>.mp4       only with --title
    preview/                the same for 540x960 previews
  out/wide/                 the wide-opening variant (same layout)
  tmp/                      render scratch, deleted after each clip unless --keep-temp
```

`<name>` is `<id>_<slug>` from clips.json.

## 4. Commands in run order

Set these once per shell:

```
K=/path/to/podcast-clipping/scripts
W=/path/to/job
```

### 4.1 Sync, roles, manifest, lip-sync check

```
python $K/ingest.py --work $W --only sync     # optional: just print the offsets
python $K/ingest.py --work $W                 # everything
python $K/check.py  --work $W lipsync         # picture vs sound at 3 points
```

- In: `shoot.json`, the mic WAVs (or videos with audio), the camera proxies.
- Out: `manifest.json`, `audio/`, `work/a16/`, `work/sync_result.json`, `work/faces.json`.
- Prints the offset and drift per camera, the role of each camera,
  the mouth-motion evidence, and every crop box.
- `lipsync` writes `work/lipsync_check.json`. Picture and sound should agree within a frame.
- Read the roles line. If a camera got the wrong person, set `"role"` in shoot.json and run again.

### 4.2 Transcribe

```
python $K/transcribe.py --work $W --peek 150   # first 150 s of each mic: whose mic is whose?
python $K/transcribe.py --work $W              # the whole recording
```

- In: `work/a16/` from ingest.
- Out: `transcript/words_host.json`, `words_guest.json`, `speech_regions.json`, `transcript.md`.
- `--range T0 T1 --out DIR` does one stretch only (for testing).

### 4.3 Plan the shots (no render)

```
python $K/render.py --work $W --id 10 --plan-only
```

- In: `clips/clips.json`, `clips/edits.json`, the transcript, the manifest.
- Out: printed only. You get the pieces, the edge checks
  (the recogniser listens to each cut edge), and the shot list with a reason per shot.
- About a minute per clip.

### 4.4 Preview render

```
python $K/render.py --work $W --id 10 --preview
python $K/render.py --work $W --all --preview
```

- 540x960 from the proxies, fast.
- Out: `out/closeup/preview/...`, every file listed in section 3.
- It already runs the heard check, the technical check and the contact sheet for each clip.

### 4.5 Contact sheet

```
python $K/check.py --work $W sheet out/closeup/10_my-best-clip.mp4
```

- Frames at 0 s, 1.5 s, the middle of each shot, and the last frame,
  labelled with the shot kind. Out: `<name>_sheet.jpg`.
- Use the captioned file so you see the captions too.
- `faces` and `eyes` cut out the guest in every listening shot,
  so you can check eyes open, looking at the speaker, and no hand over the face.

### 4.6 Heard-words check

```
python $K/check.py --work $W heard out/closeup/clean/10_my-best-clip.mp4
python $K/check.py --work $W edges out/closeup/10_my-best-clip.mp4
python $K/check.py --work $W check out/closeup/clean/10_my-best-clip.mp4
```

- `heard` recognises the whole finished clip plus a window around every seam,
  and diffs it against the intended words. Out: `<name>.heard.txt`, plus the match ratio and seam flags.
- `edges` compares the first and last 1.5 s with what was meant.
- `check` covers loudness (target -15 LUFS, true peak under -1.5 dBTP), silences, clicks at cuts,
  and picture/sound sync per shot. Out: `<name>.check.json`.

### 4.7 Captions, then the overlay

```
python $K/captions.py --work $W --id 10 --print    # look at the lines
python $K/captions.py --work $W --id 10            # write <name>.captions.json
python $K/overlay.py  --work $W --id 10            # burn: clean/<name>.mp4 -> <name>.mp4
python $K/overlay.py  --work $W --id 10 --title    # also titled/<name>.mp4 (off by default)
```

- render.py already does both steps. Use these to fix captions without re-cutting.
- You can edit `<name>.captions.json` by hand and then run only overlay.py.
- The title hook comes from clips.json `title_hook`. It is off unless you pass `--title`.

### 4.8 Full-quality render

```
python $K/render.py --work $W --all --final                      # from the 4K sources
python $K/render.py --work $W --id 10 --final --source proxy     # 1080x1920 from the proxies
python $K/render.py --work $W --id 10 --final --opening wide     # variant: wide opening
python $K/check.py  --work $W finals                             # QA table: out/closeup/finals_qa/summary.json
```

- `--final` reads each camera's `source` (a file path, or a `.url` file holding a link).
- The wide opening reuses the closeup render of the same clip (its audio and captions),
  so render the closeup version first.

### 4.9 Music checks

```
python $K/music_check.py --music music/10.mp4 --voice out/closeup/10_x.mp4
python $K/music_check.py --music m.mp4 --voice v.mp4 --highpass 250 --json m.json
```

- Use it on any version with music under it (from your editor, or mixed with ffmpeg as in `references/music.md`).
- It lines the two files up, subtracts the voice, and measures what is left (the music).
- It reports the voice level, the music median and p90,
  how far the music sits under the voice, and per-second music levels at the start and the end.
- `--highpass 250` measures only what a phone speaker plays.

### 4.10 Preview page

```
python $K/preview_page.py --spec page.json --out $W/preview_page
```

- Makes 540x960 copies and posters, then fills `templates/preview_page.html`.
- The page has a version switch (one button per "mode") and an optional "Song: ..." line.
- The encode settings are fixed (small files that load fast on a phone):
  - video: `scale=540:960:flags=lanczos`, libx264 `-preset medium -crf 27 -profile:v high -pix_fmt yuv420p -g 48`, aac 128k, `+faststart`
  - poster: `-ss 0.6 -frames:v 1 -vf scale=432:768 -q:v 5`
- Running it again only re-encodes changed files.
  A changed file gets a new name (`c10.v2.mp4`), so phones do not play a cached old copy.
- Open `index.html` in a browser. To review on a phone, put the whole output folder (`index.html` + `media/`) anywhere that serves files, or copy it to the phone.
- The spec format is in `preview_page.py --help`.

## 5. Config formats

### shoot.json

Everything per shoot. See `examples/shoot.json`.

```
{
 "title": "Show name ep. 5",
 "people": {"host": {"name": "Sam"}, "guest": {"name": "Alex"}},
 "mics": {
   "host":  {"file": "raw/wav2.wav"},
   "guest": {"file": "raw/wav3.wav"}
 },
 "cameras": {
   "camA": {"proxy": "raw/camA_proxy.mp4", "source": "raw/camA_src.url", "acoustic_delay_ms": 10.0},
   "camB": {"proxy": "raw/camB_proxy.mp4", "source": "raw/camB.mov", "acoustic_delay_ms": 7.0},
   "camC": {"proxy": "raw/camC_proxy.mp4", "acoustic_delay_ms": 7.5}
 },
 "wide": {"host_side": "left"},
 "colour": {"camB": [0.98, 1.0, 1.025]},
 "face_w_filter_4k": {"close": [300, 600], "wide": [120, 260]},
 "face_w_accept_4k": {"close": [300, 650], "wide": [120, 280]},
 "looks": {"guest_half": {"scale": 0.75, "w": 1800, "h": 1600, "face_x": 0.56, "eye_y": 0.22, "aspect": "9:8"}},
 "captions": {"font": "assets/MyBoldSans.ttf", "phrase_fixes": [[["951"], ["9:51"]]]},
 "transcript": {"ignore_until_s": 2.3, "fixes": [[["clawed", "code"], ["Claude", "Code"]]]},
 "wide_opening": {"plate_cam_time": [3552, 3578], "crop_x_limits_4k": [0, 1000],
                  "head_search_cols_proxy": [60, 520], "hair_top_range_out": [450, 760]}
}
```

Keys:

- `mics.<role>`: `file`, plus `stream` and `channel` when the audio is inside a video
  or on one channel of a multi-channel file.
  Give the same file for both roles when there is only one mixed track.
- `cameras.<cam>`:
  - `proxy`: 1920x1080, same frame rate on every camera. Made for you if missing.
  - `source`: the full-quality file, or a `.url` file with a link. Only `--final` reads it.
  - `role`: `wide`, `host_close`, `guest_close`. Leave it out to let ingest decide.
  - `acoustic_delay_ms`: the sound travel time from the people to the camera mic, about 3 ms per metre.
    It is subtracted from the measured audio offset.
  - `offset_s`, `drift_ppm`: set the sync by hand and skip the measurement.
- `wide.host_side`: `left` or `right`, which side of the wide frame the host sits on.
- `colour`: RGB gains per camera, to match skin tones to the wide.
- `face_w_filter_4k`, `face_w_accept_4k`: the face width range (pixels in 4K) that counts as a real face.
  Close-ups and the wide differ. Tune them when faces are missed or false faces appear.
- `captions.font`: the caption font file (section 9).
- `looks.guest_half`: how the guest sits in their half of a split.
  The default puts their eyes at 40% of the half. The example lifts them clear of the captions.
- `captions.phrase_fixes`: [[heard words], [caption words]], lowercase, whole recording.
- `transcript.ignore_until_s`: words before this time are dropped (crew talk at the start).
- `transcript.fixes`: [[heard], [written]] for the transcript (names, products).
- `wide_opening`: only for `--opening wide`. `plate_cam_time` is a stretch of wide-camera time
  with both chairs empty, used to find the top of the host's head.
  The crop and column limits keep the crop away from things in the room.

Paths can be absolute or relative to the job folder.

### clips.json

A list. See `examples/clips.json`.

```
[{"id": "10", "slug": "my-best-clip",
  "title_hook": "the one thing\nmost people get wrong",
  "segments": [{"start": 2877.29, "end": 2885.10}, {"start": 1589.085, "end": 1601.4}],
  "intended": "the words you expect to hear, for the checks"}]
```

Segments are master-clock seconds. They can come from anywhere in the recording, in any order.

### edits.json

Hand edits per clip id. See `examples/edits.json` (its `_doc` explains every key).

```
{"05": {
  "segments": {"0": {"cuts": [[2034.87, 2035.21]], "why": "second 'is' removed"},
               "2": {"start": 2017.205, "mics": "both"}},
  "shots": {"splits": 0, "split_at": [12.4], "cutaway_at": [8.0], "no_cutaway": [[3, 6]],
            "no_guest": [[2040.1, 2043.0]]},
  "word_fixes": [["give you an example", "i'll give you an example."]],
  "caption_patches": {"replace": [["old line", "new line"]]},
  "drop_backchannel": true}}
```

- `segments.<n>`: `start` and `end` lock an edge. `cuts` removes exact master ranges.
  `mics` is `auto`, `both` or `host` (which mics are open in that piece).
  `skip` drops the piece.
- `shots`: times are output seconds, except `no_guest`, which is master seconds.
- `word_fixes`: [heard, wanted, (who)] applied before line breaking.
- `caption_patches`: fixes on finished lines (`replace`, `merge_next`, `drop_into_next_once`).

### Outputs

- `<name>.edl.json`: `pieces` (output and master times), `shots`
  (index, out_start, out_end, frames, kind, layout, look), `words` (output times, who),
  `edge_checks`, `audio`, `plan`.
- `<name>.captions.json`: `[{"t0", "t1", "text"}]`.
- `<name>.heard.txt`: the intended text, the heard text, and the differences, with seam flags.
- `<name>.check.json`: `lufs`, `true_peak_dbtp`, silences, `guest_shots`,
  `longest_without_guest_s`, sync per shot.
- `<name>_sheet.jpg`: the contact sheet.

## 6. Which camera and which mic is whose

**Mics.** You say it in shoot.json: `mics.host` and `mics.guest`.
To check, run `transcribe.py --peek 150` and read who says what.
The manifest stores it as `mics.roles` (`{"host": "mic_host", "guest": "mic_guest"}`).

**Cameras.** Ingest decides, and you can override with `cameras.<cam>.role`.

- **Wide or close-up:** a camera that shows about two faces at once (median 1.5 or more) is the wide.
- **Which person:** ingest finds stretches where only one mic is talking,
  then measures mouth motion in each close-up. The close-up whose mouth moves with a mic shows that person.
  The numbers go into `manifest.json` `mics.evidence`.
- **Sides of the wide:** `wide.host_side`.

The manifest then holds `cameras.<cam>.role`, `subject_mic`, the sync, colour gains, and every crop box.

## 7. Other camera setups

What has been tested is marked.

- **Three cameras (wide + two close-ups): tested** on a real episode, end to end.
- **Two close-ups, no wide: planned for, not tested.**
  The planner turns off wide shots (`has_wide`). Rhythm cuts use the punch-in looks instead.
  Splits and cutaways still work, since both people have a close-up.
- **Wide + one close-up: planned for, not tested.**
  The person without a close-up is shown from their side of the wide (a crop).
  No listening cutaways or splits.
- **One camera: tested** (planning and a preview render, using only the wide camera of a three-camera shoot, two mics).
- **Four or more cameras: not supported.** Ingest takes any number of cameras,
  but the planner uses one wide and one close-up per person.
  To use a fourth camera, set its role to the one it should replace and leave the other out.
- **More than two people: not supported.** Roles are host and guest only.
- **Landscape output: not supported.** The output is 1080x1920 (or 540x960). The size is fixed in the render code.

### One camera (the single-camera method)

A single wide camera showing both people. Crops of it stand in for the close-ups.

Config:

```
"cameras": {"camA": {"proxy": "raw/camA_proxy.mp4", "role": "wide"}},
"wide": {"host_side": "left"}
```

- Ingest builds `wide_single_left`, `wide_single_right` and their `_punch` versions.
  These are tight 9:16 crops of each side.
- The planner sees no close-ups. Host shots use the crop of the host's side,
  and guest talking shots use the crop of the guest's side.
- Listening cutaways and splits are skipped, because they need close-ups of both people.
- Sync still needs the camera's own audio to line up with the mics.
- The 4K wide crop is only about 810 px wide, so it is upscaled about 1.3x for 1080x1920.
  The proxy is worse (about 2.7x). Use `--final` from the 4K source.

With **one mixed mic** (or the audio only inside the video), give the same file for both mic roles.
Then:

- Everything is recognised, and every word is labelled host.
  Nobody can tell from one track who spoke.
- Mic ducking (closing the other person's mic between lines) is skipped. There is nothing to duck.
- Camera roles cannot come from mouth motion. Set `role` by hand.
- Speaker-based shots do not work: with no guest words, the planner never cuts to the guest.
- Sync uses the same track for every camera.

What was tested:

- One camera with two mics: a preview render of one clip using only the wide camera.
  Host and guest crops alternate, the guest gets their talking shots, and the cut and sound match the 3-camera version.
- One camera with one track: simulated by giving the host mic to both roles and putting every word on the host.
  The render worked, and the heard check matched (0.969). Every shot is the host.
  A real mixed track (a camera's own audio, or a stereo mix) was not tested, and neither was ingest with one track.

Not faked: no speaker separation is attempted.

## 8. Overriding a shot by hand

**Change one shot or one cutaway.** Use `shots` in edits.json (output seconds):
`split_at`, `cutaway_at`, `no_cutaway`, `splits` (how many), and `no_guest`
(master ranges where the guest must not be shown).
Run `render.py --plan-only` to see the result.

**A whole shot list by hand.** Use `shots.force_frames`, in output frames.
The list must cover the clip from frame 0 to the last frame with no gaps.
Kinds: `R` host, `H` guest speaking, `C` guest cutaway, `S` split.
The guest shots are still checked, and you get a warning if their eyes are shut.

```
"03b": {"shots": {"force_frames": [
  [0, 86, "R", "single", "opening"],
  [86, 226, "R", "wide", "rhythm"],
  [226, 310, "S", "half", "split"],
  [310, 481, "R", "single_punch", ""],
  [481, 541, "C", "single", "cutaway hides the pause cut"],
  [541, 1300, "R", "single", ""]]}}
```

Get the frame numbers from a `--plan-only` run (seconds x fps), then edit.

**The wide opening.** `clips/wide_openings.json`, output seconds (see `examples/wide_openings.json`):

```
{"04": {"force": {"E0": 3.337, "E1": 4.755, "kind": "C",
        "why": "guest laughing with eyes open 3.34-4.75 s"}}}
```

`E0` is the end of shot 0 (the wide). `E1` is the end of the first guest shot.
Look at the frames before choosing.

## 9. Caption font

No font is bundled. Use any bold sans font file you have the right to use (.ttf or .otf).
Inter Bold or Montserrat Bold (both under the Open Font License) work well.

- A variable font is set to weight 700. A static font is used as it is, so pick the Bold file itself.
- The kit measures the text with the font you give it, so line breaks always fit that font.

The font is looked for in this order:

1. `--font` on render.py or overlay.py
2. `CLIPKIT_FONT`
3. `shoot.json` `captions.font` (absolute, or relative to the job folder)
4. `/System/Library/Fonts/SFNS.ttf` (SF Pro, on a Mac; check Apple's font licence covers your use)

If none is found, the render stops before cutting anything.
For a rough preview only, `CLIPKIT_FONT_FALLBACK=1` uses a stand-in:
Inter SemiBold/Bold if installed, else DejaVu Sans Bold.
Re-run the caption pass with your real font before delivering. It takes seconds and does not re-cut.

## 10. Frame rate

The output follows the cameras' frame rate.
Ingest reads it from the proxies (all must match) and writes `fps` to the manifest.
Every script reads it from there.

Places that still assume about 24 fps:

- Before a manifest exists, the default is `CLIPKIT_FPS`, else 24000/1001.
- Some planner timings are in frames, tuned at 23.976.
  Examples: the 3-frame lead-in on guest shots, the tighten loop's frame steps,
  and the edge checker's step size.
  At 30 fps they are a little shorter in seconds. At 60 fps they are half as long.
- Only 23.976 has been tested.

## 11. Resuming after a container restart

- A restart kills running jobs. Files already on disk survive.
- Ingest skips finished steps (sync, faces, roles). Run the same command again.
- Transcription starts over (about 10 minutes per mic-hour).
- Renders: `render.py --all --final --skip-done` skips clips whose captioned file exists
  and whose frames can be counted.
  A half-written file fails that check and is rendered again.
- Long jobs: run them in the foreground with a long timeout, or log to a file and poll.
  Do not leave them running unattended.
- Run `check.py finals` at the end to see what is complete.

## 12. Measured timings

The first job: 1 hour, 3 cameras, 2 mics, on 4 CPUs.

| Step | Time |
|---|---|
| ingest, sync only | 3 min 27 s |
| ingest, the rest (faces, roles, manifest) | 3 min 12 s |
| ingest again, everything cached | 4.5 s |
| transcribe a 3-minute stretch (both mics) | 40 s |
| transcribe the full hour | about 10 min per mic, both in parallel (old engine: 545 to 581 s per mic) |
| plan one clip (`--plan-only`) | about 1 min |
| render one clip, 1080x1920 from proxies (`--final --source proxy`) | 1 min 38 s (21 s clip), 2 min 54 s (30 s clip) |
| render one clip, 540x960 preview, one camera | 29 s (21 s clip) |
| plan the wide opening (`--opening wide --plan-only`) | 22 s, the first time (it builds the empty-room plate) |
| `check.py finals`, 2 clips | 18 s |
| `check.py lipsync` | 29 s |
| preview page, 3 files | 16 s; a re-run with nothing changed: under 0.1 s |

For comparison, the old engine logged 259 s for the same 21 s clip from the 4K sources.
A 4K `--final` render was not timed with the kit.

## 13. Gotchas

- **The recogniser's word end times run late.** Edges are refined with the VAD and the band energy,
  and the edge checker listens to each cut. Trust the edge checks, not the raw times.
- **Quiet first words get shaved.** A soft "I" or "and" at the start of a piece often goes.
  Lock the start in edits.json (`segments.<n>.start`) and say why.
- **Captions drop quiet words and keep stutters.** The transcript is not the audio.
  The heard check recognises the finished clip as a whole and diffs it against the intended words.
  Fix differences with `word_fixes` or `caption_patches`.
- **The face detector finds false faces** (posters, reflections, hands).
  The title placement and the face statistics filter by face width (`face_w_filter_4k`).
  Check the contact sheet.
- **Listening cutaways must be checked by eye:** eyes open, looking at the speaker, no hand over the face.
  The eye check helps but is not enough. Use `check.py faces` and `eyes`.
- **Signed 4K links expire.** A `.url` source works only while its link is valid.
  Proxies never expire. Test with `--source proxy`.
- **Proxies must be exactly half of the 4K source** (1920x1080 for 3840x2160).
  Crop boxes are in 4K units. `--check-sources` confirms that frame k matches.
- **The wide opening needs the closeup render first.** It copies its audio and captions.
- **A container restart kills background jobs.** See section 11.

## 14. Title hook check

```
python $K/title_check.py TITLED.mp4 UNTITLED.mp4
```

- For a title hook version made in any editor (or with `--title`), as a white box with dark text.
- Pulls the frame at 1 second, measures the white box (width, margins, centre height on screen)
  and compares the length with the version without the title.
- See `references/title-hooks.md`. The numbers catch a box that runs off the edge. They do not replace looking.
