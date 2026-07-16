# MK1 upgrade — cross-agent handoff log

Agents write requests to other agents / the orchestrator here under `### to <agent>` headings.
The orchestrator brokers anything that crosses ownership boundaries. Keep entries short + specific.

<!-- example:
### to A1 (from A4)
newRun mars branch: please initialize `b.mk1 = { bullseye: 0, medals: [] }` so scoring has state.
-->

### to A2 (from A1) — new MK1 flight envelope + predictBurnStop is now MK1-honest

The MK1 physics is retuned. Numbers your HUD/guidance should key off:
- Spawn: x ~16 km RIGHT, y ~6 km, vx ~ -215 m/s (LEFTWARD toward pad at x=0), vy ~ -15 m/s, ang ~48 deg.
- Full-throttle TWR ~2.17 at wet (9600 kg) / ~2.89 near dry. Hover throttle ~0.46 wet / ~0.35 dry.
- Total Δv ~1298 m/s; FUEL0 = 2400 kg; MDOT = 7.471 kg/s; THRUST = 3.37e4 N; DRY_MASS = 7200 kg.
- New engine model: the throttle CANNOT idle below `MK1_MIN_THROTTLE = 0.25` while lit, and slews at
  `MK1_THROTTLE_RATE = 5.5` (slower than other modes). So `b.thr` in mars is 0 (off) or in
  [0.25 .. 1.0] (lit). If you draw a throttle bar, the live floor at 0.25 is real, not a bug.
- `predictBurnStop()` now models the MK1 slower spool + min-throttle floor when `mode==='mars'`
  (previously it assumed a fast k=8 instant-ish spool with no floor). Its returned {x,y} STOP point is
  therefore a little more conservative for MK1 — the terminal-burn marker you draw should be trusted
  as an honest "where I'd arrest if I firewall now." No signature change; same {x,y} return shape.

### to A4 (from A1) — envelope numbers that affect score MEANING (you own the weights)

I own the physics feel; you own what the score means. Two of my changes touch your scoring inputs:
- FUEL0 dropped 3000 -> 2400 kg. Your `landingSpec('mars')` fuel weight is `fuelW: 0.05`, so the MAX
  fuel bonus now caps lower (2400*0.05 = 120 vs old 150). A clean flight still leaves a fat reserve
  (Δv budget ~1298 vs ~450 needed), so a full/near-full fuel medal is very achievable — but a sloppy,
  hover-heavy descent will genuinely run the tank down. If you want the fuel medal thresholds re-scaled
  to the new tank, that's your call — flag me if you want the tank resized to hit a specific score band.
- I left MK1_OK (vy<=3.5, vx<=2.5, |ang|<=6) and padHalf=30 UNCHANGED. With the new TWR 2.17 + the
  min-throttle floor, hitting vy<=3.5 now requires a well-timed arrest (real skill), which is the
  intent. If you find the touchdown gate too strict/loose against the new feel during scoring work,
  propose a tolerance tweak here and I'll re-tune the physics to match (A1 sets feel, A4 sets meaning).
