# First run: check the setup

Run this check the first time the skill is used, and again whenever something it needs is missing.

Assume the user may have opened Claude for the very first time today. Talk to them like a friend who is good with computers. Short sentences. No jargon. If you must use a technical word, say what it means in the same sentence.

## How to run the check

1. Check everything you can by looking, without asking. The table below says how.
2. Show the user one checklist. A tick for what is ready, an empty box for what is missing.
3. Under each missing item, say in one line why it is needed, then give the steps to fix it, one at a time.
4. Wait for them to say it is done, then check again. Never say an item is ready until you have checked it yourself.
5. When everything is ticked, say so in one line and move on to the job.

Fix what you can yourself. If something can be installed by running a command, run it (with their OK if their setup asks for one), rather than asking them to type it.

## The checklist

| What | Why it's needed, in plain words | How to check it |
|---|---|---|
| A Mac | The Edits app only runs on a Mac. | `uname` prints `Darwin`. |
| Claude Code | The cutting happens on your computer, and Claude Code is the version of Claude that can run things there. | You are running in it if you can run commands. |
| The clipping tools | A free toolkit that lines up your cameras, writes down every word, and cuts the clips. Installed once. | `bash scripts/setup.sh` finishes with "packages OK". It also needs ffmpeg (a free video tool) and Python 3.10 or newer. |
| The Edits app | Instagram's free video editor for Mac. It adds the music and the title hooks, with Instagram's own licensed songs and fonts. | The app is in Applications and opens. |
| Edits connected to Claude | So Claude can work inside Edits for you, instead of you clicking through it. | Edits tools are available to you (their names come from the Edits server, usually `metapilot-native`). A quick test: list Edits projects. |
| A caption font | The font the captions are written in. | A .ttf or .otf file in the job folder, or one the user points to. |
| Where to save the clips | So the finished clips land somewhere you can find them on your phone and computer. | The user has named a folder. See below. |

## Fix steps, written for the user

Use these words, or close to them. Give only the steps for what is missing.

### Install the Edits app

1. Go to edits.instagram.com and click **Download Edits**.
2. Open the download and drag Edits into your **Applications** folder.
3. Open Edits. It shows a QR code. Scan it with your phone's camera and log in with your Instagram account.

### Connect Edits to Claude

This lets me use Edits for you. It only works while Edits is open on this Mac.

1. In Edits, click your profile picture (top right), then **Settings**.
2. Click **Automation** in the menu on the left.
3. Turn on **Enable Automation Server**.
4. Under **Connect an AI client**, click **Copy** next to **Claude Code**.
5. Paste what you copied here, and I'll run it.
6. Then close Claude Code and open it again, so it can see Edits. Say "continue clipping" and I'll pick up where we left off.

What you copied contains a private key. Don't share it or post it anywhere. If it ever leaks, go back to the same page and click **Regenerate**.

When the user pastes the command, run it as given. It looks like `claude mcp add --transport http --scope user metapilot-native http://127.0.0.1:19501/mcp --header "Authorization: Bearer ..."`. Never write the key into any file, message or log other than that command, and never repeat it back.

If the Edits tools still don't show after a restart: check Edits is open, Automation is still on, and `claude mcp list` shows the server. Edits has to stay open the whole time it is being used.

### Install the clipping tools

Run `bash scripts/setup.sh` yourself. If it says ffmpeg is missing on a Mac, tell the user:

"The toolkit needs a free video tool called ffmpeg. The easiest way to get it is Homebrew, a free installer for Mac tools. Can I install both? It takes about five minutes."

Then install Homebrew from brew.sh and run `brew install ffmpeg python`, with their OK. Re-run setup.sh.

### A caption font

"Captions need a font file. If you already have a font you use on your videos, drop the file in here. If not, I'll use Inter Bold, which is free."

Inter is free under the Open Font License and can be downloaded from rsms.me/inter.

### Where to save the clips

Ask once, in these words or close to them:

"Where do you want the finished clips saved? Do you have a content folder in Google Drive, Dropbox or OneDrive? Or I can save them in a folder on this Mac."

- If they use Google Drive, Dropbox or OneDrive, the easy route is the folder that app puts on their Mac (in Finder, in the sidebar, or under `~/Library/CloudStorage/`). Saving there uploads it for them. Find the folder, show them the path, and check it with them.
- If that app isn't installed on the Mac, offer two options: install the desktop app (it is free, and you'll walk them through it), or save to a folder on the Mac for now.
- Inside their folder, make `Clips/YEAR/SOURCE NAME/`. See `delivery.md`.
- Remember their answer for the next job, if you have a way to (a memory file, project notes). Then don't ask again.

## If there is no Mac or no Edits

The clips can still be made. Say plainly what changes, in one line each:

- **No Mac:** the clipping tools also run on Linux. Music is mixed in with ffmpeg from a song file they are allowed to use, and title hooks are burned in by the toolkit. See `music.md` and `title-hooks.md`, route B.
- **Mac, but they'd rather not use Edits:** same as above, or they add music and titles in their own editor.
- **No Claude Code (only the Claude app or website):** the cutting can't run. You can still find the best moments, script each clip and write title hooks from a transcript, and hand the list to their editor.
