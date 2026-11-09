# Maintenance spending is the wrong yardstick: a pre-registered negative result for a satellite measure of road condition across 850 Nigerian highway corridors

*Jerry Bannister Zachary. Preprint, November 2026. Not peer reviewed.
DOI: [10.5281/zenodo.24081356](https://doi.org/10.5281/zenodo.24081356)*

## 1. Abstract

Can free satellite imagery tell a road agency where maintenance money should go? This paper reports a
pre-registered test of that question on 850 named Nigerian federal highway corridors, 18,419 km over
22 months at 10 m, using a verge-minus-road vegetation contrast corrected for corridor level and
season, and validated against whether a maintenance payment appears in the open procurement record.
The bar and the direction were fixed before the run: an area under the curve of at least 0.60 with the
lower bound above 0.50, and corridors with a recorded payment scoring as more degraded. The result was
0.3901, interval 0.3196 to 0.4671, wholly below 0.50. The ranking is inverted: funded corridors score
as less degraded than matched unfunded ones, and a hundred label permutations place the observed value
outside the null. The explanation offered, and not proved, is that the label is the problem. A
procurement record evidences money allocated, not road failure, and the uncorrected contrast — 0.3133,
same direction — points at road type and land cover instead. The durable
contribution is methodological: a doubly-centred score has no level, and a first attempt that averaged
one over the same corridor's months ranked missingness rather than condition. Free 10 m imagery is not
the obstacle, since published work classifies roughness from it nationally. For this question — whether
a satellite measure can rank corridors by maintenance need — allocation records are the wrong yardstick.

## 2. What the field does

The published literature on judging road condition from satellite imagery reports high accuracy. A
negative result means nothing against an unknown baseline, so this section states what the positive
results measured, on what imagery, and against what label.

**Table 1. Published performance for satellite-derived road condition, with the metric and the label
stated for each.**

| Source | Imagery | Label | Reported performance |
|---|---|---|---|
| Cadamuro et al. 2018 | 50 cm commercial, Kenya, 7,000 km of road | road-quality dataset | 88% binary accuracy; 73% five-class accuracy |
| Brewer et al. 2021 | high-resolution, US then Nigeria | platform-measured quality classes; 1,000 Nigerian images | 80.0% three-class accuracy in the US; 94.0% on Nigerian roads after fine-tuning; 99.4% within the actual or an adjacent class; ±0.32 on a 0–3 scale |
| Workman et al. 2023 | high-resolution optical, Tanzania, 83 unpaved roads, 131.7 km | ground-truth condition survey | 71.9% accuracy; 88% with a blended classifier |
| Lebaku et al. 2024 | satellite, over 3,000 images, Texas | TxDOT PMIS pavement ratings | accuracy above 90% |
| Han et al. 2023 | Google Earth aerial, 400 images, Sacramento — aerial, not satellite | city pavement condition report | 0.97 test accuracy; weighted precision/recall/F1 of 0.98/0.97/0.97 |
| Uwizera et al. 2022 | satellite, East African inter-city routes | not stated in the abstract | 99% accuracy |
| Shahri & Kim 2026 | Planet optical plus Sentinel-1 SAR | multi-year IRI | no single accuracy figure in the abstract; SAR plus optical beats either alone |
| Zhou et al. 2024 | Google high-resolution, Kenya, 1,267,818 segments | surface type, from OSM plus imagery | accuracy, recall and F1 all above 0.94 |
| Odera et al. 2025 | Sentinel-2, free, 10 m, Kenyan network | measured IRI | significant association (p < 0.05); no accuracy and no AUC |
| Thegeya et al. 2026 | Sentinel-2, free, 10 m, Philippines, 124,462 segments | roughness class | 85% binary and 71% four-class accuracy, after adding environmental covariates |

Read down the label column rather than the performance column. Every study reporting a high number
validates against a physical description of the road surface: an agency pavement rating (Lebaku et
al.), instrumented roughness (Shahri & Kim; Odera et al.), a field survey (Workman et al.; Cadamuro
et al.), a platform-based measurement (Brewer et al.), or surface type (Zhou et al.). None validates
against money.

Read down the imagery column and the pattern is consistent too. The performances cluster between 0.72
and 0.99, and almost all of them come from commercial or aerial imagery far finer than 10 m. The review literature says plainly why that matters. Schnebele et al. (2015) found
pavement damage measurement to be "often qualitative and limited to point observations", and
concluded that remote sensing "can never entirely replace traditional geotechnical methods". Herold
& Roberts (2005) found that spectral measures do correlate with pavement condition indices, but that
mapping is limited by resolution requirements "as fine as 0.5 m" and by "spectral confusion between
pavement material aging and asphalt mix erosion on the one hand and structural road damages ... on
the other". Even where the physical relationship holds, the measurement is delicate.

Two studies in this set use free Sentinel-2 at 10 m, and both are recent. Odera et al. (2025)
compared Sentinel-2 reflectance with measured IRI across the Kenyan network and found at least three
spectral signatures aligned with continuous IRI levels, with Kruskal–Wallis and post-hoc Dunn tests
significant at p < 0.05 for each. That is a report of association, not of discrimination: the
abstract gives no accuracy and no AUC, so the result cannot be placed on the axis of Table 1. Thegeya
et al. (2026) went further, on 124,462 Philippine road segments: native 10 m imagery plus ordinary
environmental covariates — temperature, precipitation, slope and population density — reached 85%
binary and 71% four-class accuracy on roughness classes, with errors concentrated between adjacent
classes. Their super-resolution experiment is the part that matters for anyone tempted to blame
pixel size: sharpened imagery looked better (PSNR 15.3 to 16.7 dB) and classified no better, with
four-class accuracy falling two to four points.

Two conclusions follow, and the second sets the terms of this paper. Free 10 m imagery is not the
obstacle: roughness has been classified from it at national scale, on 124,462 segments, against a
physical label, in a peer-reviewed study. Whatever failed in the study reported here failed
somewhere other than the pixel.

The remaining candidate is the label, and there the searches reported here found no precedent. Three
were run: a Crossref `query.bibliographic` search for "procurement records road maintenance satellite
imagery" (six results, none a validation study), an OpenAlex search for "road maintenance procurement
contract spending evaluation satellite imagery" (top seven hits unrelated — satellite procurement,
maintenance feasibility, forest road planning, data procurement), and an OpenAlex search for "road
maintenance records as ground truth label validation satellite" (top six hits, among them Workman et
al. 2023 and Thegeya et al. 2026, none using spending). No source located in those searches uses
maintenance spending, contract awards or procurement records as the validation label for a
satellite-derived condition measure. The nearest statement of the problem is motivational: Uwizera et
al. (2022) write of "a lack of accountability and validation of conventional approaches to
determining which areas to prioritize", and then validate against something else.

What is unusual about the present study is therefore a combination, not any single feature: free 10 m
imagery, fixed named corridors as the unit of analysis rather than pixels or road segments, a
22-month monthly panel, and a label derived from whether maintenance money was recorded. Scale is not
part of it. Zhou et al. (2024) cover 1,267,818 segments and Thegeya et al. (2026) cover 124,462, both
larger than the 850 corridors here.

## 3. The design

The unit of analysis is a named highway corridor: 850 of them, 18,419 km in total, observed over 22
months from September 2024 to June 2026. Corridors rather than road segments because the label has to
be joined to a name. The open road network contains large numbers of segments carrying no usable
name, so a segment-level join cannot be audited; federal corridors are named, and a named unit can be
checked by hand. The cost of that choice is coarseness, and it is accepted deliberately.

Imagery is Sentinel-2 surface reflectance at 10 m, from monthly cloud-masked composites published
openly with no account, key or payment. Collection produced 69,212 readings — one per corridor, tile
and month — which collapse to 18,700 corridor-months. Of those, 183 corridor-months across 124
corridors have no usable reading, 36 of them in more than one month, and 378 contrast values (0.55%
of the panel) are blank. Blank values are left blank. Nothing is interpolated, because a filled value
enters a ranking as though it had been observed.

Each corridor-month carries two NDVI rings: a band along the carriageway and a wider band beside it.
The measure is verge minus road. The verge is where maintenance shows — drainage, cutting, the
presence or absence of scrub closing in at the edge — while a centreline pixel samples asphalt, where
NDVI is near zero whatever the pavement is doing. A centreline-only measure therefore has no
condition signal to offer, and an earlier centreline variant of this work was abandoned for that
reason.

The contrast is strongly seasonal. On corridor means across the full 22 months it falls 38.3% between
September and December 2024, from 0.1156 to 0.0713, with no road changing. That is the calendar:
September is the end of the rains and December is the dry season, when verges lose vegetation and
dust settles on them. The regional literature treats this as a design constraint rather than a
nuisance. Philippon et al. (2007) place the dominant mode of West African vegetation variability in
August–October, tied to ITCZ convection and rainfall. Grégoire (1990) documented the effect of the dry
season on canopy condition across thirteen West African basins, and noted that thermal infrared data
may characterise changes in canopy density and vigour better than NDVI does. Horion et al. (2014)
assess long-term change in the Sahel from dry-season minimum NDVI precisely because rainy-season
greening "may mask changes in the tree–grass composition".

A variance decomposition of the raw contrast makes the same point arithmetically. Entering month
first and corridor second, the split is month 5.9%, corridor 81.2% and residual 12.8%. The order
matters and is always stated: entering corridor first gives 82.1%, 5.1% and 12.8%. Two things follow.
The residual is the only part of the variance a change measure can use, and it is 12.8% of the raw
total. And a raw level ranks when and where each corridor was photographed at least as much as it
ranks condition.

The feature is therefore a change matched on the calendar: the corridor-month contrast minus that
corridor's contrast in the same calendar month one year earlier. The corridor's own level differences
out, and so does the season. Because the panel is 22 months long, year-earlier pairs exist for 10 of
those months, so the measured change window is 10 months rather than 22. Section 7 treats that as a
limit rather than a detail.

The bar was fixed in the project's pre-registered specification before the imagery existed: an area
under the receiver-operating characteristic curve (AUC) of at least 0.60, with the lower bound of the
95% interval above 0.50. The direction was fixed before the first attempt ran — corridors with a
recorded maintenance payment should score as more degraded — and was not revised afterwards. The
distinction this protects is the one Nosek et al. (2018) describe, between analyses that follow from
predictions and analyses that follow from postdictions, noting that hindsight bias makes the second
feel like the first. Section 6 records the one revision made: to the construction of the score, not to
the bar or the direction, and why the arithmetic forced it.

The comparison sample is 644 corridors: 66 carrying a maintenance label and 578 unlabelled corridors
matched to them exactly on primary road class and on length quintile. All 66 labelled corridors
survived matching. Matching reduces the chance that the comparison is between trunk roads and rural
roads rather than between funded and unfunded ones. It cannot remove that chance.

Before this score's AUC was computed, it was put through a variability gate. It holds 850 distinct
values, 839 of them distinct at six decimal places, with a modal share of 0.2%, a standard deviation
of 0.0194, and a correlation with data coverage of −0.012. In the same run, using data coverage
itself as the score gives an AUC of 0.5089, so no instrument is quietly measuring how much imagery a
corridor has. The gate runs before the test and refuses to compute an AUC on a score that does not
vary. Section 6 explains why that ordering was not a formality.

## 4. The result and its direction

Three instruments were run on the same sample. The pre-registered primary, the year-over-year change,
gives an AUC of 0.3901 with a 95% interval of 0.3196 to 0.4671. The secondary, the slope of each
corridor's series across the months it holds, requiring at least fifteen, gives 0.4318 (0.3544 to
0.5137). The reference, the raw contrast with no correction at all, gives 0.3133 (0.2461 to 0.3881).
The bar was 0.60 with a lower bound above 0.50. The primary instrument fails on both counts, and its
entire interval lies below 0.50.

That last fact is the finding, and it is about direction rather than magnitude. AUC is a rank
statistic. With the direction fixed in advance, 0.50 means the score orders labelled and unlabelled
corridors no better than chance; a value below 0.50 means the ordering is inverted, and here the
inversion is specific: corridors with a procurement record score as *less* degraded than matched
corridors without one. It does not mean that 39% of corridors were classified correctly, and 0.3901
cannot be read as an accuracy. The same caution applies to any comparison with Table 1. Those are
classification accuracies or F1 scores over images, pixels or segments, against physical labels; this
is a rank statistic over 644 corridors against an administrative label. They are different metrics on
different tasks, and the only property safely comparable across them is direction.

One check makes the inversion difficult to dismiss as noise. A hundred label permutations give a null
distribution whose minimum is 0.4145, so the observed 0.3901 lies outside it. The difference between
labelled and unlabelled corridors is detectable, and it runs opposite to the hypothesis.

Two things are not done with this number. It is not re-read as a positive result by flipping the
direction: a reversed hypothesis would have to be written down and tested on data not used here, and
testing the mirror image of the same comparison is not a test. And it is not treated as evidence
about maintenance spending at all. What it bounds is the usefulness of this measure with this label,
which is a narrower and more checkable claim.

All three instruments sit below 0.50, and the reference — raw appearance, no correction — sits lowest.
That ordering carries the argument of the next section.

## 5. Why the label is the problem

The label comes from Nigeria's open procurement record. An entry in that record is evidence that money
was allocated to a road; it is not evidence that the road failed to perform, and it says nothing about
corridors that received nothing. The record yields 2,036 maintenance entries. Of the 1,672 put through
name matching against the road network, 181 reached a named corridor at high confidence, spread across
66 corridors. A diagnostic pass that dropped the state constraint — matching each unmatched road name
nationally rather than within its recorded state — found about 23 more. The ceiling is roughly 200
events, and it is a property of the open record, which names roads that the open road network does not
name, rather than a defect in the matcher.

Two further gaps are worth naming, because they bound what any result could mean. The label records
only that a payment exists; amounts and dates were not used in it, so a corridor funded heavily in one
year and one funded barely at all carry the same label. And an
unfunded corridor is not a control in any designed sense: it may be a road nobody needed to repair,
or a road nobody reached.

The study's own comparison points away from maintenance and towards the road itself. The raw
contrast, with no correction, separates labelled from unlabelled corridors more strongly than the
corrected measure does, and in the same direction: 0.3133 against 0.3901, both below 0.50.
Correction moves the ranking towards chance rather than away from it. If a maintenance signal lived in
within-corridor change, the change measure — which removes the season and the corridor's own level, the
two largest sources of variation in the panel — should have carried it. It carried less of the
separation than the uncorrected level did. What that shows is where the separation lives — in stable
differences between corridors — and not what those differences are made of.

That is what a confound looks like from the inside. Corridors that attract procurement records are not
a random sample of the network. Matching removes the part of that difference carried by road class and
length; it does not touch verge material or surrounding land cover, which were not measured and may
differ between a labelled corridor and the unlabelled one it is matched to. Spectral
measures of pavement are known to entangle a change in the surface with the composition of the
surface and of its surroundings. Herold & Roberts (2005) found that spectral measures correlate with
pavement condition indices while also reporting "spectral confusion between pavement material aging
and asphalt mix erosion on the one hand and structural road damages (e.g., cracking) on the other".
Radoux et al. (2016) showed that with Sentinel-2 the sensitivity of a spectral index to what is mixed
into a pixel is uneven, so an index contrast partly measures what surrounds the road. Odera et al.
(2025) found, in the same sensor and a neighbouring region, that spectral signatures align with
continuous roughness levels — which is the same statement seen from the other side: spectral class and
condition class are entangled by construction.

This explanation is consistent with the evidence and is not proved by it. Land cover and road type
were not measured per corridor, and no model here includes them. The claim is only that an inverted
ranking is better explained by what kind of road a corridor is than by what was spent on it.
Settling the question would need a land-cover covariate measured per corridor, or a label that records
condition rather than payment, and this study has neither.

The implication for the field is narrow. It is not that spending data are worthless; procurement
records are one of the few road-related datasets that are usually open, and they answer questions
about allocation and delivery. It is that a spending record cannot stand in for a condition label in a
validation design, because the two answer different questions. A study that wants to know whether
money improved a road needs a condition measure on both sides of the comparison: on the corridors that
were funded, and on the matched corridors that were not.

## 6. The methodological trap

The first version of this validation produced a score that looked like a result and could not have
been one. The reason is arithmetic, and it is worth setting out because the same step is standard
practice elsewhere.

That score removed two effects: the corridor's own mean level and the calendar-month
effect common to all corridors. Applied in sequence that is a two-way residual — the corridor-month
contrast minus the corridor mean, minus the month mean, plus the grand mean. As a residual it is a
legitimate quantity. It was not, however, the score reported in section 4. The bar and the direction
were fixed in advance; the construction of the score was revised once, after the first version was
shown to be algebraically degenerate and before any valid AUC existed. The revision changed how change
was computed — a calendar-matched year difference, not an average of the residual over a corridor's own
months — and the failure of the first version is set out here because it is reusable.

The defect was in the aggregation that followed. The validation needs one number per corridor, and the
first version obtained it by averaging the already-centred value over that corridor's own months.
Writing the residual as r(it) = x(it) − x̄(i) − m̄(t) + x̄, the average of r(it) over t for fixed i
is zero in a balanced panel: each of the four terms, averaged over the same corridor's months, reduces
to a constant that cancels. This panel is not balanced — 183
corridor-months are blank — so the average is not exactly zero, and what remains is determined
entirely by which months are missing. The ranking that emerged was a ranking of coverage.

What it produced was one value, 0.000241, on 726 of the 850 corridors, with a spread inside that
group of 7.9e-18, which is floating-point noise. The apparent AUC was 0.5735, and its correlation with
data coverage was 0.94. A score that is constant on 85% of the sample has no ranking to give; 0.5735
was ranking which corridors had missing months. It is reported here once, as a broken instrument, and
not as a finding. That value sat above 0.50, on the side of chance the hypothesis predicted, so the
revision moved the result against the hypothesis rather than towards it; the replacement was forced by
arithmetic, not chosen from a disappointing number.

The reason this belongs in a paper rather than a footnote is that the two-way residual is standard
practice, so the trap is not peculiar to this dataset. Operational vegetation monitoring has long
normalised per location and per time of year: Tadesse et al. (2010) describe a standardised seasonal
greenness computed from historical patterns at each grid cell and time of year, which is the same idea
as removing a unit effect and a calendar effect. Horion et al. (2014) achieve the same end by
restricting analysis to the dry season. Anyone who centres twice and then ranks units has built the
same trap, and a rank test on the resulting score will reward whatever drives the missingness.

What the searches reported here did not find is an account of the failure. An OpenAlex search for
"removing seasonal effects before validation vegetation index anomaly same calendar month" returned
phenology and anomaly studies, none of which validates a two-way-centred score against labels; an
OpenAlex search for "vegetation condition index Kogan percent of normal NDVI baseline" returned
normalisation methods — VegDRI, VegOut, standardised greenness — but no validation design of this
kind; and Crossref title searches on pavement and satellite validation returned none either. No
precedent was found in those searches. That is a statement about the searches, not a claim of
priority.

The rule that follows is narrow. A doubly-centred score has no level. A corridor that is always bad
and a corridor that is always good both sit near zero after two-way centring, so the score cannot
answer a cross-sectional question of the form "is this corridor worse than that one". It can answer
only a longitudinal one: "did this corridor change, relative to its own history in the same calendar
month". Validation against an external label therefore requires either a change label on the other
side of the comparison, or an uncentred level that has been checked for what else it tracks.

The gate is the operational form of that rule. It runs before the test, refuses to compute an AUC on a
score that does not vary, and requires the score to be shown to carry a ranking: 850 distinct values,
a modal share of 0.2%, a standard deviation of 0.0194, and near-zero correlation with coverage. The
general lesson is blunter than the specific one. A check that cannot fail is not a check: two tests
written earlier in this project were constructed so that no input could break them, and both were
found only by asking what input would make them fail and then running it.

## 7. What this does and does not claim

The positive claim is one sentence long. For 850 named Nigerian highway corridors, a Sentinel-2
measure corrected for corridor level and season did not rank corridors by maintenance spending in the
direction that spending would imply, and the interval lies wholly on the inverted side of chance.

It does not claim that free 10 m imagery is too coarse to measure road condition. Thegeya et al.
(2026) classify roughness from exactly that imagery, at national scale, to 85% binary and 71%
four-class accuracy after adding covariates; Odera et al. (2025) find Sentinel-2 reflectance
significantly associated with measured IRI on a neighbouring network. An argument that 10 m cannot
support this work would have to explain both away, and this paper does not attempt it.

It does not claim that maintenance spending fails to improve roads. Nothing in the design can test
that. The label records that money was allocated, not condition before and after, and the analysed
sample holds 66 labelled corridors. A negative ranking is a statement about an instrument.

It does not claim that land cover or road type caused the inversion. That is the leading explanation,
and the mechanism has published support at the level of spectrometry and of spectral mixtures, but
neither land cover nor road type was measured per corridor here. Consistency is the whole of the
claim.

It does not claim scale. Two comparators cover more road than these 850 corridors.

Five limits bound the result, and they belong in the body rather than in a footnote. The analysed
sample is 644 corridors, of which 66 are labelled; a national ranking cannot be supported by 66
positives, and the labels themselves are capped at roughly 200 events by the open record. The change
window is 10 months of the 22, because year-earlier pairs exist only there. Land-cover confounding is
a hypothesis, not a measurement. The weather layer released with the data comes from a reanalysis
licensed for non-commercial use, which restricts commercial reuse of the derived tables even though
the imagery and the code are open. And the labels are administrative, so a null result here cannot be
converted into a statement about road condition at all.

A related caution applies to the baseline rather than to this study. None of the comparator abstracts
read for Table 1 states its train/test split. Road imagery is spatially autocorrelated, so a random
split inflates apparent accuracy, and the 0.72–0.99 cluster may not survive spatial cross-validation.
That is a question to put to those papers, not a finding about them, and it should be settled before
the cluster is used as a benchmark.

Reporting the result at all rests on a contested convention. Bespalov et al. (2019) state that "there
is general reluctance to publish negative results" and propose criteria for doing so; their venue is
pharmacology, and no equivalent guidance was found for remote sensing. The criteria that matter here
are general ones. PLOS ONE's published criteria turn on technical standard, controls, a sample
"large enough to produce robust results, where applicable", and reproducibility; the page also carries
a section headed "Studies reporting negative results". The criteria read contain no requirement
regarding the sign or novelty of a finding. The design therefore has to carry the paper, which is why
the label ceiling and the 10-month window appear in section 3 rather than in an appendix.

## 8. What this leaves behind

Four things exist after this paper, and each can be checked rather than taken on trust.

**A complete national measurement.** 850 named corridors, 22 months, 10 m, 69,212 readings, every month
complete, and 183 corridor-months left missing rather than filled.

**A pipeline that costs nothing to run.** Roughly 70 GB streamed through public continuous-integration
runners, nothing stored, no payment card anywhere in the stack, and a two-month window collected in
under twenty minutes.

**Reproduction by construction.** Every row carries the run that produced it; every figure on the report
page is regenerated from its source table on each build; 91 tests run on two Python versions with no
network and no credentials; and each guard test is written so that removing the guard makes it fail.

**A method that caught its own error.** The bar, the direction and the score were all fixed before the
data existed; a variability gate stopped an algebraically empty score before it was reported; and the
failure mode is set out here so that anyone who centres twice and then ranks units can recognise it.

None of these is a result about roads. They are the reason a result about roads is now testable by
someone who holds a condition label.

## 9. Data and reproduction

The tables behind every figure are published as a dataset: 18,700 corridor-months at 10 m with weather
joined by corridor, downloadable anonymously from
<https://huggingface.co/datasets/JBZABC/roadsense-nigeria>.

The project's report page regenerates each figure from the table it came from on every build —
<https://batestguy.github.io/roadsense-nigeria/publish/> — so a reported number and its source cannot
drift apart without the build failing visibly.

Code is MIT-licensed at <https://github.com/batestguy/roadsense-nigeria>. The licence split follows
the inputs: derived tables are CC BY-SA 4.0, the reanalysis weather layer is non-commercial only, and
the read path for published data needs no token.

The test suite is 91 tests, running on Python 3.12 and 3.13 in continuous integration with no network
and no credentials. It includes the guard tests, each written so that removing the guard makes it
fail.

Imagery is collected one two-month window at a time and each window leaves a manifest, so every row
can be traced to the run that produced it.

## 10. References

Surname-only author style; DOIs as published. All sources were read at abstract level, except the
PLOS ONE criteria page, which was read in full.

- Bespalov, Steckler & Skolnick (2019). Be positive about negatives — recommendations for the
  publication of negative (or null) results. *European Neuropsychopharmacology*.
  <https://doi.org/10.1016/j.euroneuro.2019.10.007>
- Brewer, Lin, Kemper et al. (2021). Predicting road quality using high resolution satellite imagery:
  A transfer learning approach. *PLoS ONE*. <https://doi.org/10.1371/journal.pone.0253370>
- Cadamuro, Muhebwa & Taneja (2018). Assigning a Grade: Accurate Measurement of Road Quality Using
  Satellite Imagery. arXiv:1812.01699 (NIPS 2018 Workshop on ML for the Developing World).
- Grégoire (1990). Effects of the dry season on the vegetation canopy of some river basins of West
  Africa as deduced from NOAA-AVHRR data. *Hydrological Sciences Journal*.
  <https://doi.org/10.1080/02626669009492432>
- Han, Chung & Jiang (2023). PCIer: Pavement Condition Evaluation Using Aerial Imagery and Deep
  Learning. *Geographies*. <https://doi.org/10.3390/geographies3010008>
- Herold & Roberts (2005). Spectral characteristics of asphalt road aging and deterioration:
  implications for remote-sensing applications. *Applied Optics*. <https://doi.org/10.1364/ao.44.004327>
- Horion, Fensholt, Tagesson et al. (2014). Using earth observation-based dry season NDVI trends for
  assessment of changes in tree cover in the Sahel. *International Journal of Remote Sensing*.
  <https://doi.org/10.1080/01431161.2014.883104>
- Lebaku, Gao, Lu & Sun (2024). Deep Learning for Pavement Condition Evaluation Using Satellite
  Imagery. *Infrastructures*. <https://doi.org/10.3390/infrastructures9090155>
- Nosek, Ebersole, DeHaven et al. (2018). The preregistration revolution. *PNAS*.
  <https://doi.org/10.1073/pnas.1708274114>
- Odera, Ooba & Henry (2025). Exploring relationships between Copernicus Sentinel-2 multispectral data
  and international roughness index of roads in Kenya. CRC Press (book chapter).
  <https://doi.org/10.1201/9781003595120-153>
- Philippon, Jarlan, Martiny et al. (2007). Characterization of the Interannual and Intraseasonal
  Variability of West African Vegetation between 1982 and 2002 by Means of NOAA AVHRR NDVI Data.
  *Journal of Climate*. <https://doi.org/10.1175/jcli4067.1>
- PLOS ONE (n.d.). Criteria for Publication.
  <https://journals.plos.org/plosone/s/criteria-for-publication>
- Radoux, Chomé, Jacques et al. (2016). Sentinel-2's Potential for Sub-Pixel Landscape Feature
  Detection. *Remote Sensing*. <https://doi.org/10.3390/rs8060488>
- Schnebele, Tanyu, Cervone & Waters (2015). Review of remote sensing methodologies for pavement
  management and assessment. *European Transport Research Review*.
  <https://doi.org/10.1007/s12544-015-0156-6>
- Shahri & Kim (2026). Pavement Condition Assessment Using Multisource Satellite Data and Deep
  Learning. *Journal of Transportation Engineering, Part B: Pavements*.
  <https://doi.org/10.1061/jpeodx.pveng-2110>
- Tadesse, Wardlow, Hayes, Svoboda & Brown (2010). The Vegetation Outlook (VegOut): A New Method for
  Predicting Vegetation Seasonal Greenness. *GIScience & Remote Sensing*.
  <https://doi.org/10.2747/1548-1603.47.1.25>
- Thegeya, Mitterling & Njoroge (2026). Evaluating the effectiveness of satellite image
  super-resolution for road quality monitoring. *Scientific Reports*.
  <https://doi.org/10.1038/s41598-026-47749-3>
- Uwizera, Ruranga & McSharry (2022). Deep Learning Inter-city Road Conditions in East Africa
  Focusing on Rwanda for Infrastructure Prioritization using Satellite Imagery and Mobile Data.
  *SAIEE Africa Research Journal*. <https://doi.org/10.23919/saiee.2023.9962789>
- Workman, Wong & Wright (2023). Prediction of Unpaved Road Conditions Using High-Resolution Optical
  Satellite Imagery and Machine Learning. *Remote Sensing*. <https://doi.org/10.3390/rs15163985>
- Zhou et al. (2024). Mapping Road Surface Type of Kenya Using OpenStreetMap and High-resolution
  Google Satellite Imagery. *Scientific Data*. <https://doi.org/10.1038/s41597-024-03158-7>
