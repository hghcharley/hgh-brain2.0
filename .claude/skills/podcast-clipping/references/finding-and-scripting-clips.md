# Finding and scripting clips

How to choose the moments and how to build each clip's script.

The principle underneath all of it: a viewer decides in the first second whether to keep watching, and keeps deciding every few seconds after. Every line has to earn the next one. Open on something concrete that leaves a question, pay it off, and stop. If you have a short-form writing or hook-writing skill, load it too and apply it quietly. This file adds what is specific to cutting clips out of a conversation.

## What approved clips looked like

On the job this skill was built from, fourteen clips came out of 56 minutes. Read their opening lines. Each one is the host's own sentence, each is concrete, and each leaves a question open.

| Clip | Opens on | Length | What it does |
|---|---|---|---|
| 01 | "That moment there changed my life forever." | 25 s | A story. The viewer needs to know which moment. |
| 02 | "A lot of people, myself included, made a lot of money out of AI being hard to set up." | 60 s | An admission, then what it means for the viewer. |
| 03b | "It's not X, it's Y, or here's the honest truth. That was good copy." | 54 s | A contrarian take with a reason. |
| 04 | "I almost had a panic attack before I jumped on this call because I was so nervous." | 50 s | A vulnerable story with a clock ticking in it. |
| 05 | "AI is only as smart as you are." | 30 s | A hard truth, then one example. |
| 06 | "AI is not a technical skill set." | 39 s | A reframe, then what the skill really is. |
| 07 | "I don't subscribe to the whole narrative of automate out your entire business, fire everyone." | 35 s | Against the common advice, with what to do instead. |
| 08a to 08d | Four different hooks on the same answer about running ads. | 41 to 50 s | One strong clip tested four ways. |
| 10 | "[One tool]'s a Ferrari, [the other]'s a Range Rover..." | 21 s | A picture the viewer can see, then the reassurance. |
| 11 | "The last thing I wanted when I started all this was a boss." | 38 s | Why the host changed direction. The host called it "pretty much perfect". |
| 12 | "You don't owe anything any loyalty." | 38 s | Advice, landing back on the hook at the end. |

Clip 09 ("Do you know what skills are?") was dropped. It opened on a question to the guest and explained a software feature. The host: "I don't like clip number 9 at all."

## What makes a moment worth cutting

- The host is the one making the point.
- The point can be said in one sentence, and a stranger would care.
- It has a first line that works with no setup.
- It has a place to end.
- It contains something concrete: a number, a name, a time, a scene.
- It sits in the host's lane: what their channel is about. Ask the user, or read their channel, if you do not know. Stories about how they got where they are usually count.

## What gets rejected, and why

These are real reasons from the first job's shortlist. Use them as a filter.

- **It is a question to the guest.** The answer is theirs.
- **It is the guest's idea** that the host is repeating back.
- **It leans on something said earlier.** "You know how I was talking before about..." cannot open a clip.
- **It opens a loop it never pays off.** A teaser for another video is not a clip.
- **It is the line every video in the niche says.** "There's never been a better time to start."
- **It is banter**, or too short to hold an idea.
- **It is an internal pitch** for something not launched.
- **It carries factual risk.** Product names the transcript may have misheard, claims about unreleased things.
- **It trails off** into crosstalk with no ending.

Keep a separate list of the guest's best moments with timestamps and one line each. Do not cut them.

## How a script is built

A script is an ordered list of segments on the recording's timeline. Segments play in the order listed, so a later line can open the clip. Here is clip 02, trimmed to three of its seven segments.

```json
{
  "id": "02",
  "slug": "the-hard-part-is-gone",
  "segments": [
    {"start": 2563.82, "end": 2568.32, "note": "cold open, from 42:43"},
    {"start": 1593.26, "end": 1608.29, "note": "context, from 26:33"},
    {"start": 2632.91, "end": 2651.95, "note": "ending: the business owner example"}
  ],
  "notes": "what the host said about this clip, and what must be heard"
}
```

`scripts/examples/clips.json` has two worked scripts in the kit's format.

Rules for building one:

- **Start and end every segment on a complete thought.** Take times from the word timings. The kit refines the exact edge.
- **Never splice words inside a sentence.** Join whole sentences only.
- **Segments may come from far apart** if they are one thought when heard together. Clip 02 joined moments 16 minutes apart. Clip 03b ended on three lines said four to six minutes before the line it opened on. Tell the user when you do this, and which lines.
- **Write a note on every segment** saying what should be heard. The checks compare the finished audio against it.
- **Handle false starts on purpose.** If the speaker says "you you" or restarts a phrase, note which take to keep.
- **Length follows the point.** Most land between 30 and 50 seconds. A fast talker covers about 250 words a minute.

## The order of the lines inside a clip

The host's test for this work: "order the clips in a way where there's a coherent throughline and message in the short clip."

The order someone says things in is rarely the order a clip needs. In conversation people warm up, give background, then land the line. A clip needs the line first.

What a stranger needs, in the order they need it:

1. A first line that makes them want the next one.
2. Just enough context to follow it. Often one sentence.
3. The point, said plainly.
4. Something concrete that proves it: the example, the number, the scene.
5. A last line that closes the thought.

This is not a template to fill. Of the fifteen scripts on the first job, twelve played the lines out of the order they were spoken, and eleven of those opened on a line said later than what follows it. Only three played straight through. Some clips are one answer with its best line moved to the front (clip 11). Some are pieces from different parts of the hour (clip 02). Test each one by reading only the lines, in order, as someone who heard nothing else:

- Does every line follow from the one before?
- Is anything referred to that has not been said yet ("that", "it", "like I said")?
- Could a line be removed without losing anything? Remove it.
- Does the last line answer the question the first line opened?

Clip 02 as a worked case. The context came at 26:33, the admission at 42:43 and the example at 43:52. The clip plays the admission first ("A lot of people, myself included, made a lot of money out of AI being hard to set up"), then the context, then the example. Seven pieces in all. Heard in that order it is one thought. Heard in the recorded order it starts slowly and the hook is buried.

## The ending test

Play the last line and ask what the host asked: "what was the point of that video?"

- If the last line is a general statement, look at what was said next. The example is usually there.
- If the recording gives no ending at that spot, look for a line elsewhere in the conversation that closes the same thought.
- A clip can land back on its hook. Clip 12 was extended so the ending returns to the opening idea.
- A clip can end on the other person if their line is the natural close. Clip 07 ends on the guest.

## Every script correction from the first job

These are the lessons. Read them as cases, in the host's words.

**Clip 02. The ending was not tangible.**
"It's really, really good except for the last 2 seconds... 'Now I can focus on how to actually add value with AI.' But that's not really tangible. Can we continue on the clip and give some examples?"
Fix: two more segments gave the concrete example (a business owner with no ads experience who could now run that part of the business). When an ending is a promise, follow it with the proof.

**Clip 03. The key point was missing, and a bridge was in the way.**
"I also feel like we missed the key point for this video... the best copy isn't good when it becomes commoditized and accessible by everyone."
Later: "The point we're trying to drive home is... you will always need people with domain-specific knowledge... I don't like all the parts in there about 'it'd be interesting to see when the models get to a point where they're so smart'... That part can be cut out."
Fix: the thinking-aloud bridge came out. The ending became "AI is an amplifier of human taste and judgment", "It has no domain specific knowledge whatsoever", "I think that you need good people more than ever." Find the point the speaker was driving at, cut the wandering on the way to it, and end on it.

**Clip 05. Right script, rough joins.**
"It's almost perfect. Just QA it and make sure that it flows a little bit better."
Fix: every join re-cut so it sounds like one continuous thought. A good script still fails if the seams are audible.

**Clip 06. Strong first line, wrong story after it.**
"I like the first line... But then going on and talking about my friends from back home that are scared of [the tool], it's not the same vibe or angle. It's not congruent. From there, we should be talking about what I actually talked about in the pod after I said it's not a technical skill set."
Fix: rebuilt to follow what was said next. Do not attach a hook to a different story because both sound good.

**Clip 07. Good, but it needed one more line.**
"I just wonder, is there another little line we could add on the end to really drive the point home?"
Fix: one closing line added. Look for the sentence that states the takeaway outright.

**Clip 08. The host loved it, so wanted more hooks.**
"I feel as though clip number 8 is so powerful... what would be worthwhile is just playing around with 3 additional hooks."
Fix: four versions, each opening on a different one of the host's own lines from the same answer, with the same body. When the user loves a clip, offer hook versions without being asked.

**Clip 10. Good hook, not enough substance.**
"It kind of starts out calling the agents different cars, which I think is a good hook... then maybe it just needs something more to drive the point home. It's just missing some substance."
Fix: added the payoff (once you can drive one, you can drive them all). A hook plus a reaction is not a clip.

**Clip 11. Left alone.**
"Clip 11 is pretty much perfect." It was not touched again beyond the picture rules.

**First words. Audible damage at the edges.**
"It says 'that was good cop, that was good copy'. It cuts me off a little bit too early."
This is a cutting fault, covered in `audio-and-cutting.md`, but check for it when reading scripts back: quiet first words such as "I", "And", "So" get shaved.

## The batch as a whole

- Number clips in the order they appear in the recording. The numbers are names, not a posting order.
- Check the batch for repeats. Two clips making the same point is one clip too many, unless they are hook versions of the same clip (08a to 08d).
- Note which clips share a moment or a line, so they are not posted back to back. On the first job 08c opened on a line that also sat inside 05.
- If the user asks which to post first, pick the three with the strongest first lines and say why in a line each.

## Things to flag for the user, briefly

Put these in the delivery message, one line each, only where they apply.

- A number or story that belongs to the guest (on the first job, a big revenue figure was the guest's, not the host's).
- An admission the host may want to think about before posting.
- Two clips that share an answer and should not be posted back to back.
- A join between moments that were far apart.

## Title hooks

Title hooks are their own round after the clips are approved. See `title-hooks.md`. Any `title_hook` lines written into `clips.json` before then are drafts.
