# Music

Every clip gets one quiet song under it. This file is the method: how to pick the song, where it starts, how loud it sits, and how to check it.

## What the host asked for

> Add "some subtle background music" to every clip.

> A "bank of soundtrack options", with Claude able to "classify what types of soundtracks are best for what type of clip".

The references were podcast clip reels the host liked. What those reels had in common:

- One song for the whole clip.
- No build and no drop.
- Dark and low. Nothing bright.
- Music 5 to 14 dB under the voice. Louder on emotional stories, barely there on arguments.

## Keep your own bank

Keep a short list of songs you are allowed to use (licensed for your platform, or royalty-free). Five to ten is enough. For each song, record:

| Song | Artist | Use it for | Start the song at | Notes |
|---|---|---|---|---|
| (title) | (artist) | What kind of clip it suits, in a few words | Seconds into the song where it becomes audible | Licence, explicit, very soft, sub-bass only at the start, and so on |

Keep the bank in one place (a file in the job folder, or wherever the user keeps notes) and add to it when the user likes a new track. If the user has no bank yet, ask them for three to five songs they like under talking clips, and build it from those.

## Pick by what the clip is doing

Pick by what the clip is doing, not by its topic. The kinds of rows that worked on the first job:

- **A long story or thought experiment:** a flat, steady bed.
- **A warm personal moment, gentle advice:** soft and warm.
- **The most vulnerable, emotional story:** swelling strings. Big, so use it rarely.
- **Rock bottom, then the comeback:** something with more drive. Vocals are fine if they stay under the voice.
- **A hard truth, a cost, a contrarian take:** dark and low.
- **A calm argument that questions the default:** steady and slightly tense.
- **Calm mindset or philosophy:** slow and spacious.

Rules for a batch:

- Hook versions cut from the same answer share one song.
- Spread the songs across a batch. If six clips in a row are contrarian takes, they should not all get the same track.
- Many songs exist in several versions (covers, slowed, sped up, instrumental). Check the title and the artist.

## The rule that got clips sent back

> "The start is very quiet and there's no real music playing... the track only starts to be audible at around 5 to 6 seconds in."

> "The actual song doesn't seem to kick in audibly until 3 seconds in."

**The music must be audible from the clip's first second.** Most songs open quietly. Start the song past its intro.

To find a song's start point: export or extract the music alone and read its level second by second, above 250 Hz (roughly what a phone speaker plays). Start the song where that level reaches its normal running level. A song that opens on sub-bass only is silent on a phone until the rest comes in. One song on the first job opened with 5.5 seconds of sub-bass.

```
ffmpeg -v error -i SONG.mp3 -af "aresample=48000,highpass=f=250,asetnsamples=n=48000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-" -f null -
```

It prints one level per second (`pts_time` is the second). The start point is the first second near the song's typical level. Write it in the bank.

## Levels

The approved clips had the music about **11 to 16 dB under the voice**. That matches the quieter end of the reference reels.

- Keep one steady level across a batch. A clip that is louder than its neighbours stands out. Do not turn a song up because the clip is emotional.
- A soft song that measures more than 16 dB under: raise it a little.
- A song that measures less than 11 dB under: lower it.
- About 19 dB under was tried and felt very subtle. The host chose the louder setting.
- Fade in 0.5 seconds. Fade out 1.0 second. No ducking: the level is already low enough.
- The clip's own sound stays as it is.

Your ear (or the user's) decides. An agent cannot hear. Mood notes in the bank come from measurements and from what the reference reels were about.

## Adding the music

Three routes. All keep a copy of every clip without music.

**In Instagram Edits, driven by you (the default on a Mac).** Edits has Instagram's licensed song library, and posting from Edits or Instagram is the safe route for those songs. It needs the Edits app open with its automation server connected (see `first-run-setup.md`). The recipe is below, under "The Edits recipe".

**In the user's own editor** (CapCut, Premiere, DaVinci Resolve, Final Cut and so on), if they would rather do it by hand. This is the route to take when the song comes from the platform's own licensed library, which usually lives inside its app. One song per clip, starting at the song's start point, at the level above. Export at the clip's size and frame rate (1080x1920, and 24 for a 23.976 clip, 30 for a 29.97 clip). Check that the export is the same length as the clip without music.

**With ffmpeg, for a song file you are allowed to use.** The kit has no music step of its own, so use this command. It starts the song at `START` seconds, sets the music to about -28 LUFS (about 13 dB under a -15 LUFS voice), fades it in and out, and mixes it under the clip:

```
CLIP=out/closeup/01_my-clip.mp4; SONG=music/song.mp3; START=3.0; OUT=music/01_my-clip_music.mp4
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$CLIP")
FADE_AT=$(python3 -c "print(max(0, $DUR - 1))")
ffmpeg -y -i "$CLIP" -ss "$START" -i "$SONG" -filter_complex \
 "[1:a]loudnorm=I=-28:TP=-6,aresample=48000,afade=t=in:d=0.5,afade=t=out:st=$FADE_AT:d=1[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.84[a]" \
 -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k "$OUT"
```

Measure the result (below). Move `I=-28` up or down a dB or two to land 11 to 16 dB under the voice. Use the same value for the whole batch unless a song measures outside that range.

Do the music before the first delivery. The approved clips all had music, and redoing it on a recut clip takes about a minute.

## The Edits recipe

Use the Edits tools (from the Edits automation server, usually `metapilot-native`). Edits must be open. The tool list follows the screen: a short list on the home screen, the full editor set once a project is open. Tool names can change between Edits versions, so if one below is missing, list the tools and use the closest match.

Before starting:

- Edits can only read and write inside `~/Movies`. Copy the captioned clips to `~/Movies/Clips for Edits/` first, and export there too.
- One project per clip, named `SOURCE CLIPID music`, for example "Sam podcast 03 music".
- Never touch a project you did not create. Never delete or overwrite one of the user's projects.
- **Never post or publish from Edits.** The user posts.

Steps:

1. `newProject {}`. Returns the project id.
2. `renameProject {id, name}`.
3. `openProject {id, name: ""}`. Both keys are required. Do this after the rename.
4. `setCanvas {aspect: "9:16", frameRate: 24}` (or 30, to match the clip). Check with `getCanvas {}`.
5. `importToMediaPanel {path}` with the clip's full path under `~/Movies`. Returns `aliasIds`.
6. `addMediaPanelItemsToTimeline {aliasIds: [...]}`. Returns the video element id.
7. Find the song: `listMusicTracks {query: "song title artist"}`. Each row has `audioAssetId`, title, artist, duration, and flags for licensed, royalty-free and explicit. Check title and artist: search returns many versions (slowed, sped up, covers).
8. `seek {seconds: 0}` so the song lands at the start.
9. `addSongToComposition {audioAssetId}`. It comes in as long as the clip. Returns the music element id.
10. `setVolume {id, volume: 0.22}`. Adjust after measuring.
11. `setFade {id, fadeIn: 0.5, fadeOut: 1}`.
12. `setDucking {id, behavior: "none"}`.
13. Song start: `slipClip {id, deltaSeconds: START}`. This moves where in the song the clip begins. The clip's position and length stay the same.
14. `saveProject {}`.
15. `setExportSettings {resolution: "1080x1920", frameRate: 24, quality: "High", aspectRatio: "nineBySixteen", dynamicRange: "SDR", resolutionType: "HD"}`. All six keys.
16. `export {path}` to a file under `~/Movies`, then `exportStatus {}` until it reads complete.
17. Copy the file to the delivery folder as `ID_slug_music.mp4`.

Gotchas from the first job:

- After `renameProject`, the editor tools can return "Unknown tool" until the project is opened again.
- Export settings reset every time a project is opened. Set them before every export.
- `addMusicTrack` can report success and add nothing. Use `addSongToComposition`.
- `searchMusic` returns titles only. Use `listMusicTracks` for ids.
- A first export to a new folder can fail with "Cannot create file". Trying again straight after worked.
- Match the frame rate: 24 for a 23.976 clip, 30 for a 29.97 clip. Left on the default, an export came out at 60.

## Checking the result

Check every clip before delivering:

```
python scripts/music_check.py --music WITH_MUSIC.mp4 --voice WITHOUT_MUSIC.mp4 --highpass 250
```

It lines the two files up, subtracts the voice, and reports how far the music sits under the voice and the music level of each of the first seconds.

- Same length and same picture as the clip without music.
- Music 11 to 16 dB under the voice.
- The first two seconds at about the same music level as the rest. If they are quieter, move the song start later.

Check the numbers before telling the user it is fixed. On the first job, the fix for a quiet start was confirmed with a second measurement: the song went from 37 to 44 dB down for the first six seconds to 30 to 33 dB down from the first second.

## Licensing and where clips can be posted

- A song from a platform's own music library is usually cleared only on that platform, and often only when posted from its app.
- The same file posted elsewhere can get a copyright claim.
- That is why every batch also keeps a `Without music` set. Tell the user in one line which set is for where.
- Never take music out of someone else's video to use in a clip.

## If music cannot be added yet

Deliver the clips without music on the preview page. Say plainly that music is still to come and why. Add it when you can and update the page.
