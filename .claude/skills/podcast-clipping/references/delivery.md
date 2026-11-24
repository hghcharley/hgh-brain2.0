# Delivery

How the user sees the clips, where the files go, and what happens after they approve.

## The preview page

### Why

On the first job the first round arrived as video files attached in a chat. The host:

> "They have to load in."

People review on their phone, often away from the desk. One page they can tap through is the review. The full quality files live in the folder the user named.

### What is on it

- A title and one line saying what the page is.
- A row of view buttons at the top. The default set is **Music** and **No music**. Add a view only when the user has asked for a variant (a different opening, a title hook).
- One line under the buttons saying what the current view is.
- One card per clip, in id order:
  - The clip as a vertical video, with a poster image so nothing has to load before they tap.
  - The clip id and a short plain name.
  - The length.
  - In the Music view, the song and artist.
- Tapping a video plays it and pauses any other.
- The page remembers which view they were on.

Keep it quiet: lots of white space, short lines, no charts, no paragraphs. If a colour means something, say what it means on the page.

### The media

Small copies, made for the page only:

```
ffmpeg -i IN.mp4 -vf "scale=540:960:flags=lanczos" -c:v libx264 -preset medium -crf 27 \
  -profile:v high -pix_fmt yuv420p -g 48 -c:a aac -b:a 128k -movflags +faststart OUT.mp4
ffmpeg -ss 0.6 -i IN.mp4 -frames:v 1 -vf scale=432:768 -q:v 5 OUT.jpg
```

That gives 2 to 4 MB per clip. Fourteen clips in two views is about 100 MB.

Files are named by view letter and clip id: `m03b.mp4`, `c03b.mp4`, with matching `.jpg` posters.

**When a clip is replaced, the new file needs a new name.** A browser that has already loaded `m03b.mp4` will keep showing the old one. The kit's page builder does this for you by adding a version number.

### Building it

`scripts/preview_page.py` takes a short list of the clips, their names, songs and files, makes the small copies and posters, and writes the page from `scripts/templates/preview_page.html`. Its `--help` shows the list format. The output is a folder: `index.html` plus `media/`.

Getting it in front of the user:

- On the same computer: open `index.html` in a browser.
- On a phone: put the whole folder anywhere that serves files (a private web host, a shared folder the phone can open, or the agent's own way of publishing a page if it has one). Keep the link private.
- Rebuild into the same folder every time something changes, so their link keeps working.

Before sending it, open the page and check that every poster shows, one video in each view plays, and the song names are right.

### The message that goes with it

One message. Lead with the result.

- The page link (or where the page is).
- Where the full quality files are.
- What changed since they last looked, if this is a revision.
- Anything to listen for, one line each.

Short lines. White space. No recap of the process. Example of the right size:

> All 14 clips are ready, with music.
>
> Preview page: [link]
> Full quality: Clips > 2026 > [show name].
>
> Two to check: clip 02 joins two moments 16 minutes apart, and the $5.9M figure in 08 is the guest's number.

## Where the files go

Ask once where the finished clips should go, if the user has not said:

"Where do you want the finished clips saved? Do you have a content folder in Google Drive, Dropbox or OneDrive? Or I can save them in a folder on this Mac."

The simplest way into a cloud drive is the folder its desktop app puts on the computer (look in Finder's sidebar or `~/Library/CloudStorage/`). Saving there uploads it for them, with no logins for you to handle. If the desktop app isn't installed, offer to walk them through installing it, or save to a folder on the Mac for now. Remember the answer for next time if you can. A layout that worked:

```
Clips/YYYY/SOURCE NAME/With music (final)/
Clips/YYYY/SOURCE NAME/Without music/
Clips/YYYY/SOURCE NAME/With title hook/
```

- `SOURCE NAME` is short and plain: "Sam podcast", "Conference talk".
- The third folder is made in the title hook round. It holds one file per shortlisted hook.
- Keep short clips apart from long-form video folders. The long recording stays where it was.
- File names: `ID_slug_music.mp4` and `ID_slug.mp4`. Two digit ids so they sort.

**Look before you write.** List the destination before using a path. Folders get renamed by other people mid-job. If a path fails, look again before retrying.

If the files go to a cloud drive through an API or a sync folder:

- After every copy or move, list the folder and count the files.
- If a call fails, check whether the write landed before retrying. Some storage APIs return an error and write anyway.
- Never show a signed download link to the user or save one anywhere.
- To remove something, use the drive's trash, which can be undone, not a permanent delete.

## Clearing old versions

Only when the user asks, and only what they name. If what they said does not clearly cover a set of files (say, older rounds without music), ask once.

Say afterwards what was removed and whether it can be restored.

## After they approve

1. Final set into `With music (final)`. Plain copies into `Without music`. Count both.
2. Old versions removed only if they asked.
3. Update the soundtrack bank if any song or setting changed.
4. Note where the approved set lives and the page link, wherever this agent keeps project notes. A new clipping rule belongs in this skill instead (see "Improving this skill" in `SKILL.md`).
5. Give them the list of the guest's best moments if they want to pass it on.

## Things that are the user's to do

- Posting. Nothing is published from here.
- Sending anything to the guest or their team.
- Choosing between two versions they have been shown.

Everything else in this skill is covered by the request to clip the recording.
