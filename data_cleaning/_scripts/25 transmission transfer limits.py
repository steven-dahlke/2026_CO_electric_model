"""
Script 25: Zone-to-Zone Transmission Transfer Limits

Builds zone_transfer_limits.csv -- a bottom-up estimate of MW transfer capacity between each
pair of adjacent Colorado zones, derived from the physical transmission lines crossing each
zone boundary. No dataset of real zone-to-zone transfer limits exists anywhere in this project
or publicly for our specific 6-zone topology; the previous placeholder
(data_cleaning/zones/zonal transfer limits.xlsx) was only a Source/Sink adjacency list with no
MW values and no known provenance, and has been deleted as part of this work.

Scope: the 6 internal Colorado zones (Denver, North, South, East, Mountain, West) PLUS 5
polygon-based external interties (Wyoming, Utah, NewMexico, FourCorners, Nebraska) PLUS one
non-polygon external row, EasternInterconnect, representing the Lamar HVDC Tie (added
2026-08-10, closing out what had been a deliberately deferred item). "Eastern Interconnect" as a
general concept isn't a neighboring-state-style polygon at all -- it's a separate synchronous AC
grid, and Colorado's WECC territory has no direct AC tie to it, so representing the connection
means identifying specific HVDC back-to-back tie points, not a spatial boundary. Investigation
(2026-08-07, extended 2026-08-10) found three real converter stations: a real, CO-sited one --
HIFLD record with SUB_1="LAMAR HVDC TIE" (Southeast Colorado Power Association, East zone,
Prowers County; far endpoint confirmed 2026-08-09 to sit in Finney County, Kansas) -- plus two
more in the Nebraska panhandle (Virginia Smith Converter Station, David A. Hamil/Stegall DC
Tie). SIL/AC methodology doesn't apply to a DC converter tie's rated capacity, so each needed a
separately-sourced number rather than a derived one. Only the Lamar tie is included: it has a
real physical endpoint in a CO zone (same category as every other external-zone connection in
this script), and its own published Total Transfer Capability (210 MW, both directions) was
found and verified directly from its operating guide -- see `LAMAR_HVDC_TIE_MW` and
`lamar_hvdc_tie_row()` for the full sourcing and why it bypasses the usual SIL/derate steps.
Virginia Smith and Hamil/Stegall are documented but deliberately excluded -- both sit in
Nebraska, not Colorado, downstream of the same shared WECC AC pool the Nebraska external zone
already measures CO's access into; there is no way to isolate a CO-specific share of either
converter's capacity with this project's line-counting method (see the comment above
`LAMAR_HVDC_TIE_MW` for the full reasoning).

Nebraska was added 2026-08-09, after the user proposed a general design principle: if excluded
internal/external capacity is substantial (they suggested a rough ~100MW threshold), it's
worth the added model effort to represent explicitly rather than silently omit. Applying that
principle immediately surfaced a real gap -- auditing which genuine crossing lines had NO
matching built zone at all (as opposed to being merely re-bucketed) found 6 real AC lines
(115/230kV) from East zone into the western Nebraska panhandle, totaling ~213MW of derated
capacity. This is a normal AC/WECC connection (western Nebraska near Colorado is still WECC
territory per WAPA's Rocky Mountain Region footprint), NOT the same thing as the Eastern
Interconnect DC tie above -- see `build_external_zones()`'s docstring for the full sourcing,
naming verification (confirmed Nebraska, not Kansas), and why a combined "Wyoming/Nebraska"
zone was considered and rejected in favor of a separate one.

External zone geometry construction (`build_external_zones()`): Wyoming/Utah/NewMexico are
dissolved from the same nationwide `tl_2025_us_county.shp` already used for Colorado's own
zones (no new data source needed). FourCorners is built per a specific asymmetric rule the user
requested (2026-08-07), to simplify West zone's connections and avoid a separate West->NewMexico
tie: (a) the portion of New Mexico west of longitude -106.48 (everything on West zone's
southern/NM-facing border, regardless of distance -- West's segment tops out at ~-106.48, South
zone's own separate NM segment starts at ~-106.476, so this follows real geography, not an
arbitrary cutoff), unioned with (b) a 30-mile buffer around the real Four Corners Generating
Station (36.68806, -108.47694, Wikipedia -- NOT the geographic CO/UT/AZ/NM tripoint monument at
36.9989/-109.0452, which is ~47 miles away and initially caused a real line, PINTO-FOUR CORNERS,
to be wrongly excluded from the buffer before this was caught and fixed), clipped to Utah's
original polygon (only the UT-side portion of the buffer -- West's UT-facing border within 30mi
of the plant -> FourCorners; beyond it -> Utah). Both pieces are subtracted from Utah's/New
Mexico's own final polygons so no line can match two external zones by construction alone.

Methodology: identify every HIFLD transmission line whose two genuine endpoints (real
substations, not just a route that happens to pass nearby) fall in two DIFFERENT zones (any two
of the 10 -- 6 internal + 4 external), compute each line's capacity from its voltage class via
Surge Impedance Loading (SIL), sum by zone-pair, then apply a conservative derate. This is the
same general approach PyPSA-USA itself uses for the underlying line-capacity step (HIFLD line
geometry + voltage-class-derived capacity, not per-line filed ratings) -- not an ad hoc choice.
Two more-authoritative alternatives were considered and rejected: ReEDS's own inter-regional
transfer limits come from NARIS, a full power-flow study this project has no access to
reproduce; FERC Form 715 (real per-line filed ratings) would be more authoritative, but Parts
2-6 (including the ratings themselves) are CEII-restricted and not publicly downloadable
without a formal access request.

Crossing-line attribution (`build_all_crossing_pairs()`) went through substantial real
debugging (2026-08-07 through 2026-08-09) before reaching this endpoint-based design -- worth
knowing since it changed conclusions along the way, not just implementation details:

An earlier design used TWO different, inconsistent tests: internal-internal pairs via "does the
line's route intersect both zone polygons," external pairs via a separate crossing-point/far-
endpoint method. Both turned out to be wrong in the same underlying way -- crediting a zone
because a line's ROUTE happens to pass through or near it, not because the zone has an actual
electrical tap on that line. Concretely:
- PINTO-FOUR CORNERS (terminates at the real Four Corners plant) matched both Utah's and
  FourCorners' polygons at once under the old per-zone-independent external test.
- ARCHER-NORTH PARK (real endpoints Wyoming and Jackson County/Mountain zone) was credited to
  North zone under the old crossing-point test, because the wire's route happens to swing
  through/near North's territory before reaching the Wyoming line -- even though North has no
  real tap on it at all.
- Auditing all 81 then-existing internal crossing-line instances under the OLD method found 10
  (12%) with this same problem: e.g. COMANCHE-DANIELS PARK (real endpoints Denver and South)
  was double-counted toward both Denver-East and East-South, though East has no tap on it.
- Checked directly whether a "pass-through" zone can be considered to have real capacity from a
  line it doesn't tap: measured the 34.7-mile Colorado segment of PINTO-FOUR CORNERS' route --
  zero other transmission lines within 50m, zero substation endpoints (of any line) within
  2 miles. No evidence of a tap; the zone's territory being physically crossed by a wire does
  not by itself mean that zone can access the wire's capacity.

Fix: `build_all_crossing_pairs()` uses ONE consistent rule for every pair, internal or external
-- find each line's two genuine endpoints (`_line_endpoints()`), determine which of the 10 zone
polygons each endpoint actually falls in (nearest-zone, gated by `EXTERNAL_ZONE_MAX_MATCH_MILES`
so an endpoint far from every built zone -- e.g. in unbuilt Nebraska/Kansas territory --
correctly excludes the line rather than force-matching to the nearest available option), and
credit the line to that exact (zone_x, zone_y) pair if the two zones differ and at least one is
an internal Colorado zone. Deliberately does NOT pre-filter by whether zone polygons are
geometrically adjacent (an earlier `adjacent_zone_pairs()` helper, now removed) -- a line's
genuine endpoints ARE the evidence of a real tie between two zones, whether or not those zones
happen to share a mapped border; a real West<->North connection routed through Mountain's
territory (CRAIG-AULT) is a real West-North tie, not something that should be forced through
Mountain just because the zones are geographic neighbors.

The distance cutoff itself needed a real correction, not just a first guess: initially set to
20 miles (based on external-zone false positives landing 73+ miles away, since Wyoming/Utah/New
Mexico are large state polygons). That threshold turned out too loose once applied uniformly --
several East-zone-adjacent lines with real destinations in Nebraska (STEGALL, the same
DC-tie-adjacent area flagged for the deferred Eastern Interconnect item) were landing at
14.65/17.35 miles from East zone, well inside the 20mi cutoff, purely because East, being a
small internal zone, is geometrically closer to Nebraska than the large external-zone polygons
ever were. Since every genuine endpoint match found in this entire dataset lands at EXACTLY 0.0
miles (the point sits literally inside the correct zone's polygon, not merely near it), the
cutoff was tightened to `EXTERNAL_ZONE_MAX_MATCH_MILES=2` -- a real margin above 0.0 for minor
digitization slop, not a threshold tuned to produce a particular answer.

**This more rigorous, endpoint-verified method changed a conclusion the project had earlier
treated as data-validated.** The original external-zone investigation (2026-08-07) concluded
Mountain and West zones have ZERO real crossings into Wyoming, using the crossing-point method
(nearest zone to where a line's route crosses the state boundary line). That conclusion doesn't
hold under the endpoint-verified standard: Mountain zone genuinely has 2 real Wyoming ties via
its Jackson County substation (confirmed at exactly 0.0 miles from both the substation's real
location and Wyoming's polygon) -- the wire's path happens to swing close to North zone's
territory before reaching Wyoming, which is what fooled the crossing-point method, but the
actual electrical tap is in Mountain. Final verified result (2026-08-09), audited line-by-line
across all 16 zone pairs with zero remaining mismatches: North-Wyoming (7 lines), Mountain-
Wyoming (2), West-Utah (8), South-NewMexico (2), West-FourCorners (3), plus two new internal
pairs that hadn't existed under the old adjacency-filtered method -- North-West (1, the CRAIG-
AULT line) and Mountain-North (1).

Step 1 -- Surge Impedance Loading (SIL): every AC transmission line has a natural reference
loading point, SIL = V_LL^2 / Z0, where Z0 is the line's characteristic (surge) impedance.
Real-world transfer limits are consistently expressed as a multiple of a line's SIL, not an
arbitrary figure [St. Clair 1953; Dunlop, Gutman & Marchenko 1979, IEEE Trans. Power Apparatus
and Systems PAS-98(2):606-617, DOI 10.1109/TPAS.1979.319410 -- verified via Crossref, read in
full]. St. Clair, H.P. "Practical Concepts in Capability and Performance of Transmission Line,"
A.I.E.E. Trans. Part III, Vol 72(6), pp.1152-1157, Dec 1953, DOI 10.1109/AIEEPAS.1953.4498751
(also verified via Crossref).

Step 2 -- Typical SIL by voltage class: this project's transmission line source (HIFLD) records
each line's location and nominal voltage but not its specific conductor type or bundle
configuration, so standard industry-typical values are used instead of per-line specs. Sourced
via University of Wisconsin-Madison / NEOS Guide, "Estimating Line-Flow Limits" (May 1, 2013,
freely hosted at neos-guide.org -- NEOS Guide is the companion site to the NEOS Server, an
Argonne-created, now UW-Madison-hosted free academic optimization service, not a commercial
entity; no individual author found on the document, non-peer-reviewed technical note, read in
full). That document reproduces "Table 5.2" from Glover, Sarma & Overbye, "Power System
Analysis and Design" (Thomson Learning, c.2008) -- SIL ranges for all six of our voltage
classes. This project has NOT independently verified those numbers against the original
textbook (no legal free full-text access found; declined to use pirated scan sites turned up in
search) -- cite both the Wisconsin document (source actually read) and Glover/Sarma/Overbye
("as cited in" the Wisconsin document), not claiming direct primary-source verification.
Real-world corroboration (secondary, not primary sourcing): AEP (American Electric Power)
"Transmission Facts" (real utility document, ~2008-2009, read in full) cites the same
Dunlop/Gutman/Marchenko 1979 paper and gives real AEP-system loadability figures at 300 miles
for 345/500/765kV that closely match this table's long-line region for those voltages. An EPRI
report covering 115-138kV (Barthold et al. 1978) was found via the Wisconsin document's own
reference list but deliberately NOT cited here -- it only covers a strict subset of what
Glover/Sarma/Overbye's table already covers, and was never itself fetched/read, so citing it
would mean citing something unverified for zero coverage gain.

SIL_TABLE_MW below is CALCULATED, not directly quoted from the source (revised 2026-08-09,
matching a parallel revision in the writeup): the source table reports both a Z0 (characteristic
impedance) range and a SIL range per voltage class, and earlier versions of this table quoted
the source's own SIL range midpoint directly. Recomputing SIL from the source's Z0 range
midpoint via SIL = V_LL^2 / Z0 (the same formula/direction as Step 1 above -- Z0 is the primary
physical property, SIL its computed consequence) is more internally consistent with how this
script already presents the derivation, and turns the SIL figures into this project's own
calculation from a clearly-cited input rather than a second number quoted secondhand alongside
the first. Most values barely move (within rounding); 345kV and 500kV shift ~1.4-1.7% versus
the previously-quoted SIL range midpoints. 115kV has no entry in the sourced table; 69/138/230kV
all have Z0 within about 1.5% of 380 ohm (no conductor bundling below 230kV), so 115kV's SIL is
computed via the same shared-impedance formula: SIL = 115^2/380 ~= 34.8 MW. The same Z0~=380
fallback covers any other sub-230kV voltage encountered in the crossing data (e.g. 46kV, 34.5kV)
that isn't one of the six directly-sourced classes.

Step 3 -- Loadability multiplier and why a flat value is used instead of per-line length:
a line's true carrying capacity is a multiple of its SIL that depends on line length, because
different physical limits (thermal heating, voltage drop, stability) take over at different
distances -- the classic "St. Clair curve," confirmed continuous (not a step function) via
Dunlop et al.'s own Figure 7.

**History of this step, since it changed twice (2026-08-06, then 2026-08-09) and the reasoning
behind each change matters:**

*First attempt (2026-08-06): a flat multiplier, because per-line length wasn't trustworthy yet.*
At that point, "which lines cross this zone boundary" was determined by crude whole-polygon
intersection, not verified endpoints -- so a candidate crossing line's own length couldn't be
trusted either, for the same underlying reason: HIFLD's `ID` field does not group multi-segment
circuits (every CO-area row has a unique ID); `SUB_1`/`SUB_2` chaining runs substantially through
synthetic TAP#####/UNKNOWN##### placeholder names of uncertain reliability; and a pure geometric
endpoint-connectivity graph (ignoring names) showed 95% of 230kV CO-area records merging into
ONE connected mesh spanning ~5,974 miles with 93 junction/branch nodes -- meaning there was no
single well-defined "circuit length" to measure for most candidate lines at the time. Given that,
a flat multiplier (1.75x SIL, the voltage-drop-limited middle region) was applied uniformly
rather than computing a precise-looking length-based value from an untrustworthy length input.

*Second attempt (2026-08-09): length-based, once endpoints were verified.* The crossing-line
attribution method was subsequently rewritten (`build_all_crossing_pairs()`) to require each
line's own genuine endpoints to fall in the two zones being connected -- named, real substations
like Craig/Ault/Archer/North Park, not ambiguous TAP/UNKNOWN fragments. For THESE specific,
verified lines, each record's own HIFLD geometry length is a trustworthy measure of that
circuit's actual route (the earlier concern was about not knowing whether an arbitrary candidate
record represented a complete circuit or an artificial mesh fragment -- a real, named, verified
two-endpoint record doesn't have that same ambiguity). Checked directly: lengths across the 99
verified crossing lines range from 0.07 to 239 miles (median 28mi) -- nowhere near uniformly
"medium," so the flat 1.75x was materially wrong for specific real lines (e.g. the 239-mile
Craig-Ault line should be long-line-limited near 1.0x SIL, not 1.75x -- a real ~43% overstatement
under the flat approach). Switched to `length_based_multiplier()`: a continuous power-law curve
(short lines <50mi flat at 3.0x SIL; longer lines follow Smax = 42.40 * length_mi^-0.6595,
bounded to [0.5, 3.0]) sourced from the same Wisconsin/NEOS document already cited for the SIL
table, rather than reverting to a cruder 3-region step table now that continuous per-line length
is available.

**This refinement does NOT mean the resulting zone-pair totals are now a validated measure of
true aggregate transfer capability -- two separate limitations remain, one already known, one
newly worth stating explicitly:**
1. Summing individual verified-line capacities still doesn't capture how power actually
   distributes across parallel paths in a meshed network (impedance-weighted, not equal shares)
   -- the same reason real WECC path ratings run below the naive sum of their constituent lines'
   individual ratings. This is what Step 4's derate partially, generically compensates for.
2. St. Clair loadability theory itself assumes an ISOLATED two-terminal line with no
   intermediate power injection or withdrawal along its length. Given the mesh-connectivity
   finding above (95% of 230kV records forming one connected component), it's entirely plausible
   that even a verified line like the 239-mile Craig-Ault has other real circuits tapping into
   it partway along its route -- which would violate the two-terminal assumption independent of
   how that line combines with others in a zone-pair sum. Length-based precision on one line's
   own SIL multiple doesn't address this.
Net effect: this change improves each individual line's own capacity estimate, which is a real
improvement worth having, but the zone-pair totals remain a deliberate bottom-up engineering
proxy, not a power-flow-equivalent answer -- exactly as they were before this change, just with
better-justified individual inputs.

Step 4 -- Conservative derate (N-1 + aggregate stability margin): the meshed-network finding
above also means naively summing each crossing line's individual capacity likely OVERSTATES the
boundary's true aggregate transfer capability -- real WECC path ratings for a bundle of
parallel meshed lines are typically lower than the simple sum of individual line ratings,
because of system-level voltage/stability constraints on the group collectively, not just each
line's own limit. A real power-flow-study-based N-1 contingency analysis isn't achievable with
public data, so a two-part conservative multiplier is used instead, reusing sources already
cited rather than inventing a new arbitrary number:
    boundary_limit = (sum of crossing-line capacities - largest single crossing line's capacity)
                      * (1 - STABILITY_MARGIN)
1. "Total minus largest single line" -- the classic N-1 planning heuristic, handling the
   discrete "what if the single biggest circuit trips" contingency; fully computable from data
   already in hand.
2. STABILITY_MARGIN = 0.30, reused directly from the Lauria, Mottola & Quaia (2019) paper
   already read in full for the loadability methodology (Energies 12:3119, open access CC BY
   4.0, doi.org/10.3390/en12163119), which calls 30% "the commonly used value" for a
   steady-state stability margin. Applied on top of the N-1-adjusted sum as a documented,
   precedented buffer for the aggregate mesh effect a simple per-line sum can't capture on its
   own -- not a separate ad hoc concern.

**`transfer_limit_mw` represents FIRM (N-1-secure) capacity, not economic/dispatch capacity --
this distinction matters for how the CSV gets used downstream (2026-08-09).** Any zone pair
with exactly one crossing line necessarily derates to transfer_limit_mw=0 (subtracting the
"largest" line from a sum of one line leaves nothing) -- this is NOT a bug or a sign the pair
has no real interconnection. It's the methodologically correct answer for FIRM capacity: a
single circuit provides no N-1-secure capacity, because losing that one line loses the entire
tie, with no redundant path to fall back on -- standard utility planning practice, not specific
to this project. As of this write-up, `North-West` (the Craig-Ault line) and `Mountain-North`
(East Portal-Unknown205908) are real single-line ties that correctly show 0 here.

This maps directly onto a distinction EnCompass's own `AreaConn` sheet already makes (see
`encompass/Documentation/9 Input descriptions.txt`, referenced early in this whole work item):
`MaxEnLim`/`RevEnLim` is a time-varying ENERGY/dispatch limit (how much can actually flow under
normal operation), while `MaxCapLim`/`RevCapLim` is an annual FIRM capacity limit (what can be
relied upon during a contingency, used for resource-adequacy accounting). This script's
`transfer_limit_mw` (N-1 + stability-margin derated) is the natural candidate for the latter;
`raw_sum_mw` (pre-derate, still in the output for exactly this reason) is the natural candidate
for the former. Deliberately NOT resolved further here -- this script is a data-gathering step,
not the model-build step that would actually populate `AreaConn`; that future step should decide
which column feeds which EnCompass/PyPSA parameter, informed by this distinction rather than
naively treating `transfer_limit_mw` as the one true number.

Data-quality handling (two genuinely different situations, handled differently):
- `STATUS` = "NOT AVAILABLE" (locally ~74% of CO-area lines, vs. mostly "IN SERVICE" nationally
  -- reads as a data-completeness gap, not evidence of inactive lines): these lines ARE included
  in the capacity sum, tagged via `status_verified=False` for auditability. Matches this
  project's "don't silently drop data" pattern.
- Missing/unresolvable `VOLTAGE` (~4% locally): these lines have no basis for a capacity
  estimate at all (the whole method is a voltage-class -> SIL lookup) and are EXCLUDED from the
  summed capacity -- but counted per boundary (`n_excluded_missing_voltage`) rather than
  vanishing without a trace. Unverified STATUS and missing VOLTAGE are not the same situation
  and are not treated the same way.

Output: data_cleaning/zones/zone_transfer_limits.csv -- one row per zone pair: internal pairs
are unordered (Denver-North, not also North-Denver; the derivation is symmetric, a future
EnCompass/PyPSA export step can populate both directions with the same value, or apply
platform-specific asymmetry later if ever warranted -- not attempted here); external pairs are
always (Colorado zone, external zone), e.g. North-Wyoming, never the reverse. `boundary_type`
column distinguishes the two ('internal'/'external'). Columns: from_zone, to_zone,
boundary_type, n_crossing_lines, n_excluded_missing_voltage, n_status_unverified, raw_sum_mw,
largest_line_mw, transfer_limit_mw, source. **A row with n_crossing_lines=1 and
transfer_limit_mw=0 is a real single-circuit tie, not a missing/failed connection** -- check
raw_sum_mw and n_crossing_lines, not just transfer_limit_mw, before concluding a zone pair has
no physical interconnection (see the FIRM-vs-dispatch-capacity discussion under Step 4 above).
"""

import os
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT = find_project_root()
DATA_CLEANING_DIR = PROJECT_ROOT / "data_cleaning"

COUNTIES_SHP = DATA_CLEANING_DIR / "counties" / "tl_2025_us_county.shp"
TRANSMISSION_SHP = DATA_CLEANING_DIR / "transmission" / "Electric_Power_Transmission_Lines_A.shp"

ZONES_DIR = DATA_CLEANING_DIR / "zones"
OUT_CSV = ZONES_DIR / "zone_transfer_limits.csv"
OUT_CHART = ZONES_DIR / "zone_transfer_limits.png"

# Must match `1 zone_map.py`'s zone_mapping exactly -- both scripts independently dissolve the
# same county-to-zone assignment from the same source shapefile; kept duplicated rather than
# shared, consistent with this project's self-contained-script convention.
ZONE_MAPPING = {
    'Denver': ['Denver', 'Arapahoe', 'Jefferson', 'Douglas', 'Broomfield', 'Adams', 'Boulder',
               'Gilpin', 'Clear Creek'],
    'North': ['Larimer', 'Weld', 'Morgan'],
    'South': ['El Paso', 'Pueblo', 'Fremont', 'Huerfano', 'Las Animas',
              'Alamosa', 'Saguache', 'Rio Grande', 'Conejos', 'Costilla', 'Mineral',
              'Custer', 'Chaffee', 'Park', 'Teller'],
    'East': ['Logan', 'Washington', 'Kit Carson', 'Lincoln', 'Yuma',
             'Phillips', 'Sedgwick', 'Cheyenne', 'Kiowa', 'Crowley', 'Otero',
             'Bent', 'Prowers', 'Baca', 'Elbert'],
    'Mountain': ['Summit', 'Eagle', 'Pitkin', 'Grand', 'Lake', 'Jackson'],
    'West': ['Mesa', 'Montrose', 'Delta', 'Garfield',
             'Routt', 'Moffat', 'Rio Blanco', 'Gunnison',
             'La Plata', 'Archuleta', 'San Juan', 'Dolores', 'Montezuma',
             'San Miguel', 'Ouray', 'Hinsdale']
}

BUFFER_MILES = 100
BUFFER_M = BUFFER_MILES * 1609.344

# Step 2 table -- calculated via SIL = V_LL^2 / Z0, using the midpoint of each published Z0
# range (see module docstring for full sourcing; revised 2026-08-09 to source Z0 as the primary
# quantity rather than quoting the source's own SIL range midpoint directly).
SIL_TABLE_MW = {
    69: 12.4,      # V=69^2 / Z0 midpoint 383.0 ohm
    138: 49.4,     # V=138^2 / Z0 midpoint 385.5 ohm
    230: 139.2,    # V=230^2 / Z0 midpoint 380.0 ohm
    345: 368.5,    # V=345^2 / Z0 midpoint 323.0 ohm
    500: 948.8,    # V=500^2 / Z0 midpoint 263.5 ohm
    765: 2250.9,   # V=765^2 / Z0 midpoint 260.0 ohm
}
Z0_SUB_230KV = 380  # ohms, shared by 69/138/230kV (no conductor bundling below 230kV) -- used
                     # to compute SIL for any voltage not directly in SIL_TABLE_MW (115kV,
                     # 46kV, 34.5kV, etc. seen in the crossing data).

# Step 3: length-based loadability multiplier (superseded the earlier flat MEDIUM_LINE_
# MULTIPLIER=1.75 on 2026-08-09 -- see module docstring for the full history of why a flat
# value was originally chosen, and why verified real endpoints now make per-line length
# trustworthy where it wasn't before). Continuous power-law formula sourced from the
# Wisconsin/NEOS "Estimating Line-Flow Limits" document (same source already cited for the SIL
# table): short lines (<50mi) are thermal-limited at a flat 3.0x SIL; longer lines follow
# Smax = 42.40 * length_miles^(-0.6595), bounded to the source's own stated practical range
# [0.5, 3.0] (a continuous curve can otherwise produce unrealistically low values well past the
# fitted range for very long lines).
SHORT_LINE_MILES = 50
LOADABILITY_COEFFICIENT = 42.40
LOADABILITY_EXPONENT = -0.6595
LOADABILITY_MIN_MULTIPLIER = 0.5
LOADABILITY_MAX_MULTIPLIER = 3.0

STABILITY_MARGIN = 0.30        # Step 4: reused from Lauria, Mottola & Quaia (2019)

NOT_AVAILABLE_VALUES = {"NOT AVAILABLE", "", None}

# --- External zones (Wyoming, Utah, New Mexico, Four Corners, Nebraska) ---------------------
# "Eastern Interconnect" is NOT a border-length AC connection like the other five (confirmed via
# direct investigation, 2026-08-07) -- Colorado's WECC territory has no synchronous tie to the
# Eastern Interconnection along its east border. The real WECC<->EI connections nearby are
# discrete HVDC back-to-back converter stations, so SIL/AC methodology can't estimate their
# capacity the way it does for every other row -- see LAMAR_HVDC_TIE_MW below and
# `lamar_hvdc_tie_row()` for how the one CO-attributable tie is instead handled with a directly
# cited rating.
EXTERNAL_STATE_FIPS = {'Wyoming': '56', 'Utah': '49', 'NewMexico': '35', 'Nebraska': '31'}

# Lamar HVDC Tie -- real, CO-sited (Prowers County, East zone; HIFLD SUB_1="LAMAR HVDC TIE"),
# back-to-back DC converter connecting Xcel's Public Service Co. of Colorado (PSCo, WECC/West)
# to Xcel's Southwestern Public Service Co. (SPS, Southwest Power Pool/Eastern Interconnection)
# via a Lamar<->Finney County, KS path. Commercialized May 2005. Value is the tie's own
# published Total Transfer Capability, both directions -- "available 5-210 MW ->East, 5-210 MW
# ->West" / "TTC 210 MW->East, 210 MW->West" -- from the Lamar HVDC Tie (PSCo) Operating Guide,
# 8/31/2005 (Kevin Pera), read in full via pypdf; corroborated by Xcel's 2005 commercialization
# announcement and an SPP OASIS long-term-service filing for the same 210 MW figure.
#
# Independently corroborated by a modern, peer-reviewed source (2026-08-10): McCalley et al.,
# "A 2030 United States Macro Grid: Unlocking Geographical Diversity to Accomplish Clean Energy
# Goals" (Iowa State University/Breakthrough Energy Sciences, Jan 2021; arXiv:2211.10574),
# Table 3, lists Lamar's existing/"previous" capacity as 210 MW -- read directly via pypdf, not
# a search summary. That table's own caption attributes its "previous capacity" column to "the
# preliminary findings from the NREL Seams Study," i.e. Bloom, Novacheck, Brinkman, McCalley et
# al., "The Value of Increased HVDC Capacity Between Eastern and Western U.S. Grids: The
# Interconnections Seam Study," IEEE Trans. Power Systems, 37(3):1760-1769, 2022 (DOI
# 10.1109/TPWRS.2021.3115092) -- confirmed peer-reviewed via its OSTI journal-article record,
# not just the NREL technical-report preprint. Repeated attempts to pull the identical table
# directly from the Seams Study's own PDFs found no extractable "Lamar" text (table likely
# rendered as an image, or lives in a different report volume) -- citing the Macro Grid report
# as the document actually read, same "as cited in" honesty already used for Glover/Sarma/
# Overbye via the Wisconsin document. Two independent institutional sources, ~15-17 years apart,
# agreeing on 210 MW is stronger evidence than either alone.
#
# Cited directly rather than run through the SIL/length-multiplier/N-1-derate machinery built
# for unrated AC line bundles -- this is a single DC facility with its own real engineered
# rating, not something to estimate, and the N-1 "subtract the largest line" step would zero out
# any one-line set regardless of whether the tie is actually constrained (see
# `lamar_hvdc_tie_row()`).
#
# Two more real WECC<->EI converters were found and investigated (2026-08-10) but are NOT
# included: Virginia Smith Converter Station (200 MW, Sidney, Cheyenne Co., NE -- WAPA, built
# 1988, Wikipedia) and the David A. Hamil / Stegall DC Tie (Stegall, NE -- owned by Tri-State
# G&T, operated by WAPA). Stegall's rating has two disagreeing sources, noted here rather than
# silently picking one since it doesn't affect this project's numbers either way (excluded
# regardless): 110 MW per Reikofski, C., "Stegall 110 MW asynchronous HVDC tie,"
# Transmission & Distribution World, vol. 29, no. 3, pp. 14-16, 1977; vs. 100 MW per the same
# McCalley et al. 2021 Macro Grid Table 3 that corroborates Lamar's 210 MW above. Both sit in
# Nebraska, not Colorado, downstream of the same shared WECC AC pool that the East-Nebraska zone
# already measures CO's access INTO (confirmed directly against the crossing-line data: none of
# East-Nebraska's real lines share a substation with either converter). Two different cuts
# through the network in series, not in parallel -- no double-counting risk, but also no way to
# isolate what share of either converter's capacity is Colorado's specifically (it's shared with
# Wyoming, South Dakota, and Nebraska's own local generation) using a zone-boundary line-counting
# method. Documented here, deliberately excluded, rather than silently omitted.
LAMAR_HVDC_TIE_MW = 210.0

# Real Four Corners Generating Station / substation near Fruitland, NM (36.68806, -108.47694,
# Wikipedia) -- NOT the geographic CO/UT/AZ/NM tripoint monument (-109.0452, 36.9989), which is
# ~47 miles away. The actual transmission hub this external zone represents is the power plant,
# confirmed 2026-08-07 after the tripoint coordinate wrongly excluded the real PINTO-FOUR
# CORNERS line (which literally terminates at a substation named "Four Corners") from the
# buffer -- using the plant's real location fixes this.
FOUR_CORNERS_POINT_LONLAT = (-108.47694, 36.68806)
FOUR_CORNERS_BUFFER_MILES = 30  # user-confirmed (2026-08-07): within this radius of the point
                                  # on West zone's UT-facing border -> Four Corners; beyond -> Utah
# User-confirmed (2026-08-07): everything on West zone's NM-facing (southern) border goes to
# Four Corners regardless of distance, eliminating a separate West->NewMexico connection.
# South zone's own NM-facing crossings (a real, geographically separate segment -- see module
# docstring) remain their own South->NewMexico connection. West's segment tops out at ~-106.48
# longitude (confirmed in investigation); South's starts at ~-106.476 -- essentially contiguous,
# so this split follows real geography rather than an arbitrary cutoff.
NM_FOURCORNERS_SPLIT_LON = -106.48


def build_co_zones() -> gpd.GeoDataFrame:
    """Dissolve CO counties into the 6 zones, matching `1 zone_map.py` exactly. Returns a
    GeoDataFrame indexed by zone name, reprojected to EPSG:3857 (meters) for spatial ops."""
    counties = gpd.read_file(COUNTIES_SHP)
    co_counties = counties[counties['STATEFP'] == '08'].copy()

    county_to_zone = {c: z for z, cs in ZONE_MAPPING.items() for c in cs}
    co_counties['ZONE'] = co_counties['NAME'].map(county_to_zone)
    unmapped = co_counties[co_counties['ZONE'].isna()]
    if len(unmapped) > 0:
        raise ValueError(f"Unmapped CO counties: {unmapped['NAME'].tolist()}")

    zones = co_counties.dissolve(by='ZONE', aggfunc='first')
    return zones.to_crs(epsg=3857)


def build_external_zones() -> gpd.GeoDataFrame:
    """Build Wyoming, Utah, NewMexico, FourCorners, and Nebraska polygons (Eastern Interconnect
    -- i.e. the Lamar HVDC Tie / Kansas direction -- deliberately excluded, see module docstring
    / constants comment above; a DC converter tie needs separately-sourced capacity, not the
    AC/SIL methodology this script uses). Returns a GeoDataFrame indexed by external zone name,
    in EPSG:3857 to match `build_co_zones()`.

    Nebraska was added 2026-08-09 after auditing which genuine Colorado-zone crossing lines had
    no matching built external zone at all (i.e. were being silently excluded, not merely
    re-bucketed) -- found 6 real AC lines (115/230kV) from East zone with far endpoints
    confirmed via county lookup to sit in the western Nebraska panhandle (Chase, Deuel, Cheyenne
    counties), totaling ~213MW of derated transfer capacity, comfortably above the user's
    ~100MW materiality threshold for "worth representing explicitly." Deliberately named
    "Nebraska" alone, not "Nebraska/Kansas" -- checked and confirmed none of these 6 lines'
    endpoints are in Kansas (only the separately-deferred Lamar HVDC Tie's endpoint is, in
    Finney County -- that stays excluded regardless of whether a Kansas zone existed, since it
    needs different, non-SIL-based methodology either way). Considered and rejected merging
    this into a combined "Wyoming/Nebraska" zone: the three connections into it (Mountain,
    North, East) would each still need their own independent capacity regardless of how the
    target zone is labeled -- merging saves no real model complexity, only breaks the
    established one-zone-per-neighboring-geography pattern already used for Utah/NewMexico/
    FourCorners, and forecloses future differentiation (state policy, market pricing) for no
    benefit.

    Four Corners is built as the union of two pieces (see module docstring for the sourcing
    behind this asymmetric rule, confirmed with the user 2026-08-07):
      (a) the portion of New Mexico west of NM_FOURCORNERS_SPLIT_LON (everything on West zone's
          southern/NM-facing border, regardless of distance -- eliminates a separate
          West->NewMexico connection by construction, not by filtering results after the fact)
      (b) a FOUR_CORNERS_BUFFER_MILES buffer around the real Four Corners point, clipped to the
          original Utah polygon (only the UT-side portion -- West's UT-facing border within this
          radius goes to Four Corners, beyond it stays Utah)
    Both pieces are then subtracted from Utah's and New Mexico's own polygons so no line can be
    double-counted in two external zones.
    """
    counties = gpd.read_file(COUNTIES_SHP)

    wy = counties[counties['STATEFP'] == EXTERNAL_STATE_FIPS['Wyoming']].union_all()
    ut = counties[counties['STATEFP'] == EXTERNAL_STATE_FIPS['Utah']].union_all()
    nm = counties[counties['STATEFP'] == EXTERNAL_STATE_FIPS['NewMexico']].union_all()
    ne = counties[counties['STATEFP'] == EXTERNAL_STATE_FIPS['Nebraska']].union_all()

    # NM split (native lon/lat CRS, EPSG:4326 -- counties shapefile's own CRS) -- the split
    # longitude is a real geographic coordinate, so this must happen before any reprojection.
    from shapely.geometry import box
    minx, miny, maxx, maxy = nm.bounds
    nm_west_of_split = nm.intersection(box(minx, miny, NM_FOURCORNERS_SPLIT_LON, maxy))
    nm_final = nm.intersection(box(NM_FOURCORNERS_SPLIT_LON, miny, maxx, maxy))

    # Reproject everything to EPSG:3857 (meters) for the buffer step and final geometry.
    to_3857 = lambda geom: gpd.GeoSeries([geom], crs='EPSG:4326').to_crs(epsg=3857).iloc[0]
    ut_3857 = to_3857(ut)
    nm_west_3857 = to_3857(nm_west_of_split)
    nm_final_3857 = to_3857(nm_final)
    fc_point_3857 = to_3857(gpd.points_from_xy(
        [FOUR_CORNERS_POINT_LONLAT[0]], [FOUR_CORNERS_POINT_LONLAT[1]])[0])

    fc_buffer_3857 = fc_point_3857.buffer(FOUR_CORNERS_BUFFER_MILES * 1609.344)
    fc_from_utah_side = ut_3857.intersection(fc_buffer_3857)
    ut_final_3857 = ut_3857.difference(fc_buffer_3857)
    fourcorners_3857 = nm_west_3857.union(fc_from_utah_side)

    wy_final_3857 = to_3857(wy)
    ne_final_3857 = to_3857(ne)

    zones = gpd.GeoDataFrame(
        {'geometry': [wy_final_3857, ut_final_3857, nm_final_3857, fourcorners_3857, ne_final_3857]},
        index=pd.Index(['Wyoming', 'Utah', 'NewMexico', 'FourCorners', 'Nebraska'], name='ZONE'),
        crs='EPSG:3857',
    )
    return zones


def load_co_transmission(zones_3857: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Load HIFLD transmission lines, clip to a 100-mile buffer around the CO zones (same
    buffer convention as `1 zone_map.py`), reproject to EPSG:3857."""
    print("  Loading HIFLD transmission shapefile (nationwide, ~60-75s)...")
    trans = gpd.read_file(TRANSMISSION_SHP)
    trans['VOLTAGE'] = pd.to_numeric(trans['VOLTAGE'], errors='coerce')
    trans_3857 = trans.to_crs(epsg=3857)

    co_boundary = zones_3857.geometry.union_all()
    buffer_poly = co_boundary.buffer(BUFFER_M)
    clipped = gpd.clip(trans_3857, buffer_poly)
    print(f"  {len(clipped)} transmission features within {BUFFER_MILES}-mile buffer of CO zones")
    return clipped


def voltage_to_sil(voltage: float) -> float:
    """SIL (MW) for a given nominal voltage (kV). Uses the directly-sourced table for the six
    primary EHV/HV classes (nearest match within 5kV, to tolerate e.g. 500.0 vs 500), otherwise
    falls back to the shared sub-230kV impedance formula (see module docstring)."""
    for v, sil in SIL_TABLE_MW.items():
        if abs(voltage - v) <= 5:
            return sil
    return voltage ** 2 / Z0_SUB_230KV


def length_based_multiplier(length_mi: float) -> float:
    """Loadability multiplier (multiple of SIL) as a function of a line's real length -- see
    the module-level constants comment for the formula's sourcing. Short lines are flat
    thermal-limited; longer lines follow the continuous power-law curve, bounded to the
    source's own stated practical range."""
    if length_mi < SHORT_LINE_MILES:
        return LOADABILITY_MAX_MULTIPLIER
    raw = LOADABILITY_COEFFICIENT * length_mi ** LOADABILITY_EXPONENT
    return min(LOADABILITY_MAX_MULTIPLIER, max(LOADABILITY_MIN_MULTIPLIER, raw))


def compute_line_capacities(lines: gpd.GeoDataFrame) -> tuple[pd.DataFrame, int]:
    """Per-line capacity for lines with a known VOLTAGE; returns (dataframe, n_excluded) where
    n_excluded is the count of lines with missing/unresolvable VOLTAGE (logged, not silently
    dropped, but they contribute no capacity -- see module docstring). Capacity uses each
    line's own real length (trustworthy now that crossing lines have verified endpoints -- see
    `length_based_multiplier()` and module docstring for why this superseded a flat multiplier)."""
    known = lines[lines['VOLTAGE'].notna()].copy()
    n_excluded = len(lines) - len(known)

    known['sil_mw'] = known['VOLTAGE'].apply(voltage_to_sil)
    known['length_mi'] = known.geometry.length / 1609.344
    known['loadability_multiplier'] = known['length_mi'].apply(length_based_multiplier)
    known['capacity_mw'] = known['sil_mw'] * known['loadability_multiplier']
    known['status_verified'] = ~known['STATUS'].isin(NOT_AVAILABLE_VALUES) & known['STATUS'].notna()
    return known, n_excluded


EXTERNAL_ZONE_MAX_MATCH_MILES = 2  # sanity cutoff -- see build_all_crossing_pairs(). Tightened
# from an initial 20mi (2026-08-09): every genuine endpoint match found in this dataset lands
# at EXACTLY 0.0 miles (the point sits literally inside the correct zone polygon), while a real
# false-positive was found at 14.65mi -- STEGALL, NE (the same Nebraska-panhandle DC-tie-adjacent
# area flagged earlier) was being misattributed to East zone simply because East, being a small
# internal zone, was the nearest BUILT zone to a point that's actually in unbuilt Nebraska
# territory. 20mi was sized against external-zone false positives (73+ miles, since Wyoming/
# Utah/New Mexico are large state polygons), but doesn't protect against this smaller-scale
# internal-zone version of the same problem. 2mi keeps a safety margin above 0.0 for minor
# digitization slop while rejecting anything genuinely outside all 10 built zones.


def _line_endpoints(geom) -> tuple:
    """First/last vertex of a line geometry, handling both LineString (the common case) and
    MultiLineString (a real minority case in this HIFLD dataset -- some records are digitized
    as multiple disconnected parts under one row). For MultiLineString, uses the first vertex
    of the first part and the last vertex of the last part as the overall endpoints -- an
    approximation, but adequate here since these feed a nearest-zone lookup, not an exact
    length calculation."""
    if geom.geom_type == 'MultiLineString':
        parts = list(geom.geoms)
        return Point(parts[0].coords[0]), Point(parts[-1].coords[-1])
    coords = list(geom.coords)
    return Point(coords[0]), Point(coords[-1])


def build_all_crossing_pairs(lines: gpd.GeoDataFrame, internal_zones: gpd.GeoDataFrame,
                              external_zones: gpd.GeoDataFrame
                              ) -> dict[tuple[str, str], gpd.GeoDataFrame]:
    """Assigns EVERY transmission line to exactly one (zone_x, zone_y) pair -- covering both
    internal-internal and internal-external pairs with ONE consistent method, in a single pass
    across all lines. Supersedes an earlier design that used two different tests: internal pairs
    via "does the line's route intersect both zone polygons," external pairs via a crossing-
    point/far-endpoint method. That inconsistency caused real, verified errors (2026-08-09):

    1. **The internal-internal polygon-intersection test didn't require a genuine tap in either
       zone.** Auditing all 81 internal crossing-line instances found 10 (12%) where the line's
       real endpoints didn't match the zone-pair it was credited to -- e.g. COMANCHE-DANIELS
       PARK (real endpoints Denver and South) was double-counted toward both Denver-East and
       East-South, because its route happens to brush East zone's territory even though East has
       no actual tap on it. Same issue as PINTO-FOUR CORNERS below, just not yet fixed there.

    2. **A per-external-zone-independent intersects test let one line match multiple zones at
       once.** PINTO-FOUR CORNERS (terminates at the real Four Corners plant) touched Utah's
       polygon along its route through Utah territory too, so checking each external zone
       separately double-counted it.

    3. **A line needs exactly ONE genuine endpoint in each of the two zones it's credited to --
       not just a route that happens to pass through/near a zone's territory.** CRAIG-AULT (both
       real Colorado towns -- West and North zones respectively) still registered as
       "intersecting" Wyoming's and Mountain's polygons due to an HIFLD digitization quirk in
       its path; PINTO-FOUR CORNERS turned out to have NEITHER endpoint in Colorado at all (one
       in Utah, one at the New Mexico plant) once checked properly -- verified directly (checked
       the 34.7-mile Colorado segment of its route for any other line within 50m or any
       substation endpoint within 2mi -- found zero of either), confirming it's a genuine
       Utah-to-New-Mexico transit line with no accessible tap for West zone, not an assumption.

    4. **Endpoints far from every zone we've modeled need to be rejected, not force-matched to
       the nearest available option.** Several East zone lines (real Nebraska-panhandle
       circuits, plus the real "LAMAR HVDC TIE" itself) have true destinations in Nebraska/
       Kansas -- the deliberately-deferred Eastern Interconnect direction, with no built zone
       polygon -- and were force-matching to Wyoming at 73-361 miles away without a cutoff.
       `EXTERNAL_ZONE_MAX_MATCH_MILES` = 20 rejects these (every genuine match in this dataset
       landed at exactly 0.0 miles, so this is a wide safety margin, not a tuned threshold; it
       applies to internal-zone matches too, though internal zones fully tile Colorado so a
       genuine in-Colorado endpoint is always ~0 miles from its zone regardless).

    This method does NOT pre-filter by whether zone polygons are geometrically adjacent (the
    old `adjacent_zone_pairs()` test, now removed). A line's two genuine endpoints are
    themselves the evidence of a real electrical tie between whichever two zones they fall in --
    if that pair doesn't happen to share a mapped border (e.g. a line rooted in West but ending
    in North, passing through Mountain's territory with no real Mountain tap), the correct
    electrical representation is a direct West-North connection, not one artificially routed
    through Mountain just because the zones are geographic neighbors. Excluded: lines with both
    endpoints in the same zone (not a tie), lines where neither endpoint matches any of our 10
    zones within the cutoff, and lines where neither matched zone is one of the 6 internal zones
    (an external-to-external line that never actually involves Colorado).
    """
    all_zones = pd.concat([internal_zones, external_zones])
    internal_names = set(internal_zones.index)
    max_match_m = EXTERNAL_ZONE_MAX_MATCH_MILES * 1609.344
    zone_order = list(internal_zones.index) + list(external_zones.index)

    def nearest_zone(pt):
        name = min(all_zones.index, key=lambda n: all_zones.loc[n, 'geometry'].distance(pt))
        return name if all_zones.loc[name, 'geometry'].distance(pt) <= max_match_m else None

    result: dict[tuple[str, str], list] = {}
    for idx, row in lines.iterrows():
        p0, p1 = _line_endpoints(row.geometry)
        z0, z1 = nearest_zone(p0), nearest_zone(p1)
        if z0 is None or z1 is None or z0 == z1:
            continue
        if internal_names.isdisjoint({z0, z1}):
            continue  # external-to-external line, doesn't involve Colorado at all

        # Internal zone (if only one is internal) always listed first; if both internal, use
        # ZONE_MAPPING's insertion order for a stable, consistent from/to designation.
        if z0 in internal_names and z1 not in internal_names:
            pair = (z0, z1)
        elif z1 in internal_names and z0 not in internal_names:
            pair = (z1, z0)
        else:
            pair = (z0, z1) if zone_order.index(z0) < zone_order.index(z1) else (z1, z0)

        result.setdefault(pair, []).append(idx)

    return {key: lines.loc[idxs] for key, idxs in result.items()}


def _boundary_summary(capacities: pd.DataFrame) -> tuple[float, float, float, int]:
    """Shared aggregation logic: sum, largest line, N-1 + stability-margin derated transfer
    limit, and count of status-unverified lines -- used by both internal and external paths."""
    n_status_unverified = int((~capacities['status_verified']).sum())
    if len(capacities) == 0:
        return 0.0, 0.0, 0.0, n_status_unverified
    raw_sum = capacities['capacity_mw'].sum()
    largest = capacities['capacity_mw'].max()
    transfer_limit = max(0.0, (raw_sum - largest) * (1 - STABILITY_MARGIN))
    return raw_sum, largest, transfer_limit, n_status_unverified


def _boundary_row(zone_a: str, zone_b: str, capacities: pd.DataFrame, n_excluded: int,
                   boundary_type: str) -> dict:
    raw_sum, largest, transfer_limit, n_status_unverified = _boundary_summary(capacities)
    return {
        'from_zone': zone_a, 'to_zone': zone_b, 'boundary_type': boundary_type,
        'n_crossing_lines': len(capacities),
        'n_excluded_missing_voltage': n_excluded,
        'n_status_unverified': n_status_unverified,
        'raw_sum_mw': round(raw_sum, 1),
        'largest_line_mw': round(largest, 1),
        'transfer_limit_mw': round(transfer_limit, 1),
        'source': 'hifld_voltage_sil_medium_line_n1_stability_derate',
    }


def _print_boundary_row(zone_a: str, zone_b: str, capacities: pd.DataFrame, n_excluded: int) -> None:
    raw_sum, largest, transfer_limit, n_status_unverified = _boundary_summary(capacities)
    single_line_note = (
        " [single-circuit tie -- 0 is correct FIRM capacity, not a missing connection; "
        "see raw_sum_mw]" if len(capacities) == 1 and transfer_limit == 0 else ""
    )
    print(f"    {zone_a}-{zone_b}: {len(capacities)} lines, "
          f"raw_sum={raw_sum:.0f}MW, largest={largest:.0f}MW, "
          f"transfer_limit={transfer_limit:.0f}MW"
          + (f", {n_excluded} excluded (missing voltage)" if n_excluded else "")
          + (f", {n_status_unverified} status-unverified" if n_status_unverified else "")
          + single_line_note)


def lamar_hvdc_tie_row() -> dict:
    """East -> EasternInterconnect, representing the Lamar HVDC Tie. Deliberately bypasses
    `build_all_crossing_pairs()`/`compute_line_capacities()`/`_boundary_summary()` -- those
    exist to estimate capacity for an unrated bundle of AC lines from voltage class and length,
    which doesn't apply here: this is a single DC facility with its own real, cited rating (see
    `LAMAR_HVDC_TIE_MW`). Schema matches `_boundary_row()`'s output so it can be appended
    directly to the same table, but every derived field (raw_sum/largest/transfer_limit) is set
    to the same cited value rather than computed, and `source` is tagged distinctly so this row
    is never mistaken for one of the SIL-derived estimates."""
    return {
        'from_zone': 'East', 'to_zone': 'EasternInterconnect', 'boundary_type': 'external',
        'n_crossing_lines': 1,
        'n_excluded_missing_voltage': 0,
        'n_status_unverified': 0,
        'raw_sum_mw': LAMAR_HVDC_TIE_MW,
        'largest_line_mw': LAMAR_HVDC_TIE_MW,
        'transfer_limit_mw': LAMAR_HVDC_TIE_MW,
        'source': 'named_hvdc_tie_rated_ttc',
    }


def build_boundary_table(lines: gpd.GeoDataFrame, internal_zones: gpd.GeoDataFrame,
                          external_zones: gpd.GeoDataFrame) -> pd.DataFrame:
    """Builds the transfer-limit table for every (zone_x, zone_y) pair with at least one
    genuine crossing line, covering internal-internal and internal-external pairs together via
    `build_all_crossing_pairs()`'s single consistent attribution method -- see that function's
    docstring for the full rationale and the real errors this replaced."""
    by_pair = build_all_crossing_pairs(lines, internal_zones, external_zones)
    internal_names = set(internal_zones.index)

    rows = []
    for (zone_a, zone_b), crossing in by_pair.items():
        capacities, n_excluded = compute_line_capacities(crossing)
        if len(capacities) == 0:
            continue
        boundary_type = 'internal' if zone_b in internal_names else 'external'
        rows.append(_boundary_row(zone_a, zone_b, capacities, n_excluded, boundary_type))
        _print_boundary_row(zone_a, zone_b, capacities, n_excluded)

    lamar_row = lamar_hvdc_tie_row()
    rows.append(lamar_row)
    print(f"    {lamar_row['from_zone']}-{lamar_row['to_zone']}: 1 line (DC tie), "
          f"transfer_limit={lamar_row['transfer_limit_mw']:.0f}MW "
          f"[cited TTC, not SIL-derived -- see LAMAR_HVDC_TIE_MW]")

    return pd.DataFrame(rows)


def plot_transfer_limits(df: pd.DataFrame, out_path) -> None:
    with plt.rc_context({"font.family": "Times New Roman", "font.size": 18}):
        fig, ax = plt.subplots(figsize=(10, 6))
        labels = df['from_zone'] + "-" + df['to_zone']
        ax.bar(labels, df['transfer_limit_mw'], color='#4ECDC4', edgecolor='black')
        ax.set_ylabel("Transfer Limit (MW)")
        ax.tick_params(axis='x', rotation=45)
        ax.spines[['top', 'right']].set_visible(False)
        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
    print(f"  Chart -> {out_path.name}")


def main() -> None:
    print("\n--- Script 25: Zone-to-Zone Transmission Transfer Limits ---")

    print("\n[1/5] Building Colorado zone polygons...")
    zones_3857 = build_co_zones()

    print("\n[2/5] Building external zone polygons (Wyoming, Utah, NewMexico, FourCorners, Nebraska)...")
    external_3857 = build_external_zones()

    print("\n[3/5] Loading transmission line data...")
    # Buffer around internal zones only, same as before -- external zone polygons extend well
    # past this buffer in places (e.g. all of Wyoming/Utah/New Mexico), but crossing lines only
    # need to be found near Colorado's own border, so the existing 100-mile buffer is more than
    # sufficient and keeps this step fast; no need to re-clip against the external polygons too.
    lines = load_co_transmission(zones_3857)

    print("\n[4/5] Identifying crossing lines and computing transfer limits per boundary...")
    boundary_df = build_boundary_table(lines, zones_3857, external_3857)

    ZONES_DIR.mkdir(parents=True, exist_ok=True)
    boundary_df.to_csv(OUT_CSV, index=False)
    print(f"\n  Saved: {OUT_CSV.relative_to(PROJECT_ROOT)} ({len(boundary_df)} rows)")

    print("\n[5/5] Saving diagnostic chart...")
    plot_transfer_limits(boundary_df, OUT_CHART)

    print("\nSummary:")
    print(boundary_df.to_string(index=False))


if __name__ == "__main__":
    main()
