# What 18,700 satellite readings could not do for Nigerian roads

## The question

Nigeria allocates money to federal roads every year, and the open procurement record shows it:
roughly 2,000 maintenance entries since 2021. What the record does not show is which roads are
getting worse. A contract proves that money was allocated. It does not prove that a road failed,
and it says nothing at all about the roads nobody funded.

Satellites are free and they are monthly. Sentinel-2 photographs the country at 10 metres, and
Digital Earth Africa publishes those images already composited and cloud-masked — no account, no
key, no payment. That makes a narrow question answerable: can the way a road looks from space say
which corridors are deteriorating fastest, and does it agree with where the money went?

## What was built

850 corridors. 18,419 km of named highway, roughly half the federal network. 22 months, from
September 2024 to June 2026. 69,212 satellite readings at 10 metres, one for every corridor, tile
and month. 18,700 corridor-months once those tiles are averaged into a single value per corridor
per month, with 183 corridor-months missing and left missing rather than filled in.

Getting there took 2,016 tiles, 96 parallel jobs and repeated collection runs, each of which leaves
a manifest in the published data. Two months took 17 minutes and 51 seconds end to end. The full
22 months is about one to three hours and roughly 70 GB streamed, with nothing stored. It runs on
free tiers with no payment card anywhere in the stack, which was a constraint, not a boast.

The measurement is a contrast. For each corridor and month there are two rings: a band along the
carriageway and a wider band beside it. Both are NDVI, a standard greenness index. The value is
verge minus road. A maintained corridor has tidy verges and working drainage; a failing one has
dust, bare laterite and scrub closing in at the edges. The centreline on its own measured tarmac:
mean NDVI on sampled Lagos corridors came back at or below zero, one bridge at −0.081. Asphalt is
not vegetation, so a centreline reading was never going to work.

## The trap

The contrast moves with the calendar. On corridor means across all 22 months it falls 38.3% between
September and December 2024, from 0.1156 to 0.0713, with no road changing. September is the end of
the rains. December is the dry season, when verges lose vegetation and dust settles on them.

It moves with land cover too. Lagos corridors average between +0.008 and +0.023; the national mean
is +0.13. The likely reason is that Lagos verges are concrete and dirt while national verges are
grass, but that explanation is a hypothesis and has not been measured. Whatever the cause, a raw
level cannot be compared across seasons or states, and a national table of them would be a table of
when and where each road was photographed.

The variance tells the same story. With month entered first and corridor second, 5.9% of the raw
variance sits between months and 81.2% between corridors, leaving 12.8% as residual — the only part
a change measure can use. Enter corridor first and the split becomes 82.1 and 5.1, which is why the
order is stated rather than implied. It also shows plainly that weather, land cover and registration
differences all live in that last 12.8%.

So the feature is per corridor: the contrast minus the same corridor's value in the same calendar
month one year earlier. The corridor's own level differences out, and so does the season.

The first attempt at this failed in the most expensive way a number can. It produced a score that
took one value, 0.000241, on 726 of 850 corridors, with a spread inside that group of 7.9e-18,
which is floating-point noise. It looked like a result. It could not have been one: a score that is
constant on 85% of the sample has no ranking to give. A gate now refuses to run any test until the
score is shown to vary, and it refuses before the test rather than after it.

## The test

The bar was written down before the test ran. An area under the curve of 0.60 or more, with the
lower bound of the interval above 0.50, and the direction fixed in advance: corridors with recorded
spending should score as more degraded.

The result was 0.3901, with an interval of 0.3196 to 0.4671. A second instrument — the slope of each
corridor's series across the months it holds, requiring at least fifteen — gave 0.4318. The reference,
raw appearance with no correction at all, gave 0.3133.

All three sit below chance. The interval does not straddle 0.50; it lies to the wrong side of it.
Corridors with a procurement record score as *less* degraded than comparable corridors without one,
which is the opposite of a maintenance signal and cannot be read as one. Whatever the contrast is
picking up, more spending is not what it tracks.

Some things were checked before that could be believed. Each instrument was tested for having enough
distinct values to rank anything, and all three passed. Using data coverage itself as a score gave
an area under the curve of 0.5089, so none of the three is quietly measuring how much imagery
exists. The merge is keyed on corridor, tile and month, and the duplicate count is asserted at zero
rather than assumed.

The labels are also thin, in a way that limits what any answer could mean. The procurement record
yields 2,036 maintenance entries. Of the 1,672 events put through matching, 181 reached a named
corridor at high confidence, spread across 66 corridors. A diagnostic pass that dropped the state
constraint and re-scored every unmatched event nationally found about 23 more. The ceiling is
roughly 200, and it is a property of the open data — the record names roads that the open road
network does not name — rather than a defect in the matcher.

## What it means

Not that no signal exists. The claim is narrower and more useful: this measure, with these labels,
cannot allocate maintenance. Sixty-six positive cases cannot support a national ranking, and a
residual carrying only 12.8% of the variance does not leave much room to work in. The honest
inference is about the instrument, not about the roads.

That is the finding worth publishing. A score of 0.3901 is dull. The alternative, reporting the
mirror image of the same data and calling it a model, would have been easy and dishonest; it would
also have survived a casual read. The pre-registered direction is what makes that impossible to do
by accident.

## What survives

Four things, in descending order of how much they are worth.

The dataset: 18,700 corridor-months at 10 metres, with weather joined by corridor, published under
CC BY-SA 4.0 and downloadable anonymously —
[huggingface.co/datasets/JBZABC/roadsense-nigeria](https://huggingface.co/datasets/JBZABC/roadsense-nigeria).

The page that reports the failure, with every figure regenerated from the file it came from on each
build — [batestguy.github.io/roadsense-nigeria/publish](https://batestguy.github.io/roadsense-nigeria/publish/).

The pipeline: a backfill that runs nationally in about three hours on free infrastructure, and
manifests that say which window produced which row.

And a method. A bar set before the test. A gate that catches a constant score. A label ceiling
measured rather than assumed. None of that is clever, and all of it is what a number needs before
anyone should act on it.

---

## Sources

Every figure above traces to one of two files. The lines below name each figure and where it lives.

- 850 corridors, 18,419 km, 22 months: `docs/publish/index.html` (lede and "How the measurement
  was made"); `docs/findings.md` F12 and F20.
- 69,212 readings at 10 m: `docs/publish/index.html`, "What was checked" — completeness row.
- 18,700 corridor-months, 183 missing: `docs/publish/index.html`, "How the measurement was made"
  and the variance figure table (18,517 used).
- 2,016 tiles, 96 shards, 17 min 51 s, ~70 GB, 1–3 hours: `docs/findings.md` F18, F20, F21.
- Free tiers, no payment card: `docs/findings.md` F5 and F6.
- `−0.081` on one Lagos bridge: `docs/findings.md` F17.
- 38.3%, 0.1156 to 0.0713: `docs/publish/index.html`, seasonal figure; `docs/findings.md` F22
  (complete-series note).
- Lagos +0.008 to +0.023, national +0.13: `docs/findings.md` F19 and F22.
- 5.9 / 81.2 / 12.8 and 82.1 / 5.1: `docs/publish/index.html`, variance figure and its table.
- 726 of 850, 0.000241, 7.9e-18: `docs/publish/index.html`, "The broken instrument".
- 0.60 bar, 0.3901, 0.3196–0.4671, 0.4318, 0.3133, 644 / 66 / 578, 0.5089, 850 distinct values:
  `docs/publish/index.html`, instruments figure table and "What was checked".
- 2,036 maintenance entries: `docs/findings.md` F13.
- 1,672 events, 181 matched, 66 corridors, ~23 more, ceiling ~200: `docs/findings.md` F11.
