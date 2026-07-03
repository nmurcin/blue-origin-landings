# Reachable landing-X envelope — REAL-GAME empirical findings

All numbers below are from the REAL game (headless Chrome + DevTools bot: bot_sweep.py
/ bot_envelope.py, active-steering controller in bot_autopilot's successor bot_sweep
controller_js). No offline sim was trusted. Spawns are randomized by the game
(ocean x=-(13500±800), vx=450±40, vy=-(480±60); tower x=-(15000±1000), vx=550±50,
vy=-(600±60)) plus random wind, so every run differs — landing points are BANDS.

## The two control levers (verified to move the landing point in the real game)

1. DECEL / ENTRY BURN amount (retrograde, engines-to-wind): more braking = bleed more
   energy = land SHORTER. The entry burn is also the game's MANDATORY reentry mechanic:
   a hot entry (esp. tower) BURNS UP unless total speed is bled before the dense-air/
   heat band (~11 km down). Tower cannot survive without it.
2. Body TILT: strake lift is perpendicular to velocity ("bank to turn"). A downrange
   lean would extend range, BUT at hypersonic entry speed any off-retrograde attitude
   raises angle-of-attack -> heat -> BURNUP. So in practice the survivable attitude is
   RETROGRADE (belly/engines to wind) through entry; tilt is only usable low & slow.
   Net: for a survivable descent the dominant lever is the BURN, not tilt.

Also discovered (and fixed): up high in near-vacuum there is no aero damping, so naive
bang-bang steering TUMBLES the vehicle (ang swung 20°→-170°→+140°...), which then
enters the air broadside and burns up. The controller now RATE-DAMPS attitude (PD on
angv) and holds true retrograde before the heat band. This was the root cause of the
earlier tower "mid-air abort" (it was a burnup, dmg=100, not a landing).

## OCEAN (7×2) — reachable landing-x envelope   [padHalf 44, OK vy≤8.5 vx≤4? (7.0)]

Two regimes (real runs, each soft touchdown vy≈-3, vx≈0, upright, vx never reversed):

  A) NO entry burn (heat-MARGINAL — burns up on hot spawns): converges SHORT, x≈7000–8300.
     BRAKE_HARD→7011(dmg65)  MED→7560(80)  SOFT→7919(80)  LIGHT→8181(79)  MIN→8282(70)
     COAST_MIN→8139(67). dmg 65–80 = survives on mild spawns, but a hot spawn pushes
     dmg→100 (burnup). NOT reliable.
  B) WITH a mild entry decel burn (entryDecelSpd≈340) — ROBUST, dmg=0 every run:
     converges to x≈13,400–15,100 (3-run reps: 14194/14470/14610 tight; another batch
     13384/13999/15138). Always survives, soft, vx never reverses.

So the SURVIVABLE-AND-REPEATABLE ocean landing zone is ~13,400–15,100 (regime B). Regime A
(≈7,000–8,300) exists but is heat-marginal — a competent flier who wants to survive
every spawn lands in regime B.

## TOWER (9×4) — reachable landing-x envelope   [padHalf 34, OK vy≤6.0 vx≤4.0]

Tower REQUIRES the entry decel burn (hot entry). Survivable runs (dmg=0, soft, vx never
reversed), landing set by entry-brake amount:
  EDECEL_180→15,711 (fuel 8.7k, near-max brake)   EDECEL_240→16,489
  EDECEL_300→17,365   EDECEL_360→19,621
  entryDecelSpd≥430 (too little brake) → BURNUP (dmg=100). 
3-run rep at a moderate brake: 17,222 / 17,653 / 17,898 (tight ~676 m spread).
Tower survivable zone ≈ 15,700–19,600, converging ~17,200–17,900 for a moderate brake.

## Deck-ahead + vx-never-reverses: PROVEN (gap = deckX - booster_x over time)

TOWER, deck=17,250, a converging run (bot_run_tower_TWDECK1.json):
  t= 5s x=-12955 gap=30205   (deck 30 km AHEAD at spawn — far, faithful)
  t=35  x=  -422 gap=17672
  t=65  x= 10014 gap= 7236
  t=95  x= 16246 gap= 1004
  t=115 x= 16996 gap=  254
  t=134 x= 17214 gap=   36
  touchdown x=17222 gap=28  -> min in-flight gap = 28 (>0: DECK AHEAD WHOLE DESCENT)
  min vx over flight = -0.6 (vx NEVER reversed; +498 → +0.5 monotone toward the deck)
  touchdown vy=-3.3, vx=0.5, ang≈0, offset 28 < padHalf 34  => ON DECK, in tolerance.

OCEAN, deck≈14,000, a converging run (bot_run_ocean_OCDECK1.json, landed 13,999):
  t= 5s x=-11899 gap(→14000)=25899   (deck ~26 km ahead at spawn)
  t=45  x=  1679 gap= 12321
  t=85  x= 11642 gap=  2358
  t=115 x= 13688 gap=   312
  touchdown x=13999 gap≈+1   -> deck ahead until the final ~100 m; vx +416→0, never reverses;
  vy=-3.2, upright.

## RECOMMENDATION (real-game-derived)

- OCEAN (7×2): deckX ≈ **14,000**  (near the short edge of the robust survivable band
  13,400–15,100). Deck is ~26 km ahead at spawn and stays ahead until touchdown; vx
  never reverses; touchdown vy≈-3, vx≈0, upright, dmg 0, ~16 k kg fuel left.
- TOWER (9×4): deckX ≈ **17,000**  (near the short edge of the survivable band
  15,700–19,600). Deck ~30 km ahead at spawn, stays ahead to touchdown; vx never
  reverses; touchdown vy≈-3, vx≈0, upright, dmg 0, ~12 k kg fuel left.

## The hard tradeoff to flag (deck-ahead + reachable-IN-PADHALF cannot BOTH hold every run)

The deck-ahead-the-whole-way and vx-never-negative properties hold ROBUSTLY. But padHalf
is only 44 m (ocean) / 34 m (tower), while the game's spawn randomization + wind produce
~±400–900 m of landing scatter for a fixed control strategy. So a FIXED deck is hit
within padHalf on SOME runs (e.g. the tower run above, offset 28) but not EVERY run —
the residual scatter exceeds the pad. Hitting the 44/34 m pad on every random spawn
requires active closed-loop terminal guidance that nulls the gap to the exact deckX;
the bot's terminal deck-seek helps but has limited low-altitude authority, so it lands
in a tight band around the deck rather than dead-center every time.

Closest achievable: place the deck at the SHORT edge of the tight survivable band
(ocean ~14,000, tower ~17,000). Then essentially every competent descent reaches the
deck (lands AT or just past it), the deck is ahead the whole way, vx never reverses, and
a well-flown run lands within padHalf; the spawn-scatter tail lands a few hundred m long
(still downrange, deck still behind at touchdown — never a reversal).

Note these decks are FAR downrange (~14–17 km) vs the current game values (7,050 /
8,350). The current tower deck at 8,350 is effectively UNREACHABLE by a survivable
descent — the booster burns up or runs out of brake authority long before it can stop
that short. This matches the earlier finding that the offline sim (deck_geometry_both.py,
which predicted ~7,050/8,350) does not model the real game's heat/energy budget.
