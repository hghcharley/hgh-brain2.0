# Captions

Every clip carries captions. The default style is deliberately plain: white text with a soft drop shadow, no box, one short line at a time. If the user already has a caption style of their own, use theirs and change the numbers in `scripts/clipkit/overlay.py` (`CAP`) to match. Otherwise use this one.

## The look

On a 1080x1920 frame:

| | |
|---|---|
| Font | A bold sans at weight 700 (Bold), letter spacing 0. |
| Size | 50 px |
| Text colour | Solid white |
| Shadow | Black at 55% opacity, 3 px down, 4 px blur. Just enough to read over a light background. |
| Box | None. No outline, no border. |
| Position | Centred. The line's middle sits at y 1440, 75% down the frame (the caption band is y 1408 to 1472). |
| Motion | None. Hard cuts between captions. |
| Emphasis | None. No highlighted words, no colour, no emoji. |

Before captioning a batch, render one test frame (`overlay.py --test-frame`) and look at the text size, shadow and position. If the user has an approved clip in their own style, compare with a frame from it (`--ref`).

Over a very bright background, white text can get lost. Raise the shadow opacity (`shadow_alpha` in `CAP`) a little before reaching for a box.

## The font file

No font is bundled with this skill. Fonts have licences, so use one the user has the right to use.

- Any bold sans .ttf or .otf works. Inter Bold or Montserrat Bold (both free under the Open Font License) look clean. Check the licence of any font before burning it into videos you publish.
- A variable font is set to weight 700. A static font is used as it is, so pass the Bold file itself.
- Tell the kit where it is: `--font PATH` on `render.py` or `overlay.py`, or `CLIPKIT_FONT`, or `captions.font` in the job's `shoot.json`. Copy the font into the job folder at the start of the job, so every step finds it. Without a font the kit stops before cutting anything.
- The kit measures text with the font it is given, so line breaks and box widths always fit that font.
- If no font is to hand yet, `CLIPKIT_FONT_FALLBACK=1` uses a stand-in (Inter or DejaVu Sans, if installed) for rough previews only. Say the captions are drafts, and re-run the caption pass once the font is in place. The caption pass takes seconds because it does not re-cut.

## The words

- **One short line at a time.** Two to five words, about 26 characters at most.
- **All lowercase.** The one exception is "AI", because "ai" reads badly. Product names are lowercase too: "chatgpt", "claude", "canva".
- **No full stop or comma at the end.** Keep apostrophes. Keep "$", "%" and digits.
- **Numbers as digits:** "$5.9 million", "2pm", "500", "9:50".
- **Break at natural phrase edges.** Never leave one stray word if it can join a neighbour.
- **Both speakers get captions.**

Examples from approved clips:

```
AI is only as smart
as you are
```

```
that moment there
changed my life forever
```

If the user prefers sentence case, change it everywhere. Do not mix.

## Timing

- A caption appears on the frame its first word starts.
- It stays until the next caption starts.
- After the last word of a segment, or before a pause, it goes within 0.15 seconds.
- Timing comes from the word timings carried through the cut, so captions move with every edit.

## Fixing the text by hand

Captions built from word timings are wrong in predictable ways. Fix every clip before burning in.

- **Quiet words get dropped:** "i", "had", "the", "a".
- **Stutters and false starts stay in.** If the cut removed a doubled word, remove it from the caption. If a restart was kept on purpose, caption only the clean take.
- **Misheard words.** Real ones from the first job:
  - "marketing agents here" should be "marketing agency"
  - "something will snapped" should be "something snapped"
  - "which has seen me 3,000 people" should be "which is going to be 3,000 people"
  - "9:50 / 951 / 952" should be "9:50", "9:51", "9:52"
- **Names of tools and people.** Check the spelling of anything unusual against what the product or person is actually called.

How to check: recognise the finished clip as a whole and compare it line by line with the caption text (`check.py heard`). Then read the captions through once as a viewer with the sound off. They should make sense on their own.

## Two files per clip

- A clean cut with no text.
- The captioned clip, made by laying captions over the clean cut.

Write the caption text to its own file before burning it in. A wording fix then means editing that file and re-running the caption pass. Nothing is re-cut.

Put lasting fixes in the job's hand-edits file as well (`word_fixes` and `caption_patches` in `clips/edits.json`). A fix made only in the caption file is lost the next time that clip is re-cut.

## Captions inside a phone editor

Phone editors offer a fixed set of caption looks, and the size and position usually cannot be set exactly. Burn the captions in with the kit before the clip goes to any editor. Use the editor for music or titles only.

## Safe area

Instagram, TikTok and Shorts cover the bottom of a vertical video with the caption and buttons, and the top with the header. The caption line at 75% down sits clear of both. Keep any other text between y 250 and y 1350.
