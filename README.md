# BLUE ORIGIN LANDINGS

A free, single-file browser rocket-landing game inspired by Blue Origin hardware.

> **Unaffiliated fan / educational project.** Not affiliated with, endorsed by, or sponsored by
> Blue Origin. Every vehicle figure is derived from **publicly available data** and tuned for
> gameplay — none of it is an official Blue Origin specification.

## What it is

Vanilla JavaScript + HTML5 Canvas 2D + Web Audio. **One self-contained `.html` file**, no build step,
no dependencies, no network calls — open it in any modern browser and play.

### Missions
1. **New Glenn 7×2** — land the seven-engine first stage on the sea platform *Jacklyn* (LPV-1).
2. **New Glenn 9×4** — the heavier nine-engine variant; steeper, faster, tighter, leaning on the
   strakes' cross-range glide.
3. **Blue Moon MK1** — set the uncrewed lander down on the Moon (vacuum, 1/6 g, Apollo-style approach).

### Realism tiers (in progress)
A picker selects the physics fidelity:
- **Arcade** — compressed, legible arcade physics with a realistic-reading HUD.
- **Moderate** — believable separation altitudes/speeds.
- **Full Sim** — full real-scale entry (hypersonic, atmospheric braking).

## Run it

Open `index.html` (or `blue_origin_landings.html`) in a browser. Dev shortcut:
`index.html?play=ocean` / `?play=tower` / `?play=mars` jumps straight into a mission.
Press **P** to pause (resumes where you left off), **X** for 2× fast-forward.

## Files

- `index.html` — the game (canonical copy; `blue_origin_landings.html` is the working name).
- `blue_origin_landings_{A,B,C}_*.html` — scale-variant prototypes (being folded into the tier picker).
- `scripts/trace_vehicles.py`, `render_grade.py` — the OpenCV vehicle-art tracer + IoU grader that
  generate the in-game vector silhouettes from reference images. Run `py scripts/trace_vehicles.py`.
- `scripts/bo_landings_*.py` — headless physics sanity sims (MDOT/TWR derivation, glide/landability checks).

## Credits

Game framework derived from the open "LANDING BURN" browser game; re-skinned and re-physics'd for
Blue Origin vehicles. Vehicle art auto-traced from publicly available reference renders.
