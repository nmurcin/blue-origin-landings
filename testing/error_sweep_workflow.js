export const meta = {
  name: 'bo-landings-error-sweep',
  description: 'Adversarial error-analysis sweep of the 2D NG landing game: fan finders across code regions, verify every finding with independent skeptics, return only confirmed bugs',
  phases: [
    { title: 'Find', detail: 'one finder per code region + a cross-cutting logic finder' },
    { title: 'Verify', detail: 'independent skeptics per finding (correctness + intended-behavior lenses)' },
    { title: 'Synthesize', detail: 'dedupe, rank, completeness critic' },
  ],
};

const FILE = 'C:/Users/nmurcin/Lumen/local/blue-origin-landings/index.html';

// Compact "intended behavior — do NOT flag" list distilled from
// testing/PHYSICS_CONVENTIONS.md + testing/FIDELITY_ASSESSMENT.md. Finders must
// treat these as CORRECT-BY-DESIGN and never report them as bugs.
const DONT_FLAG = `
INTENDED BEHAVIOR — do NOT report any of these as bugs (they were audited 2 days ago and are correct-by-design):
- Frame convention: +x right, +y UP, ground y=0. ang=0 means nose points +y (up). Nose unit=(sin(ang),cos(ang)); tail=-(sin,cos); body normal=(cos,-sin). Screen y-flip lives ONLY in w2sY/curveOff; physics never sees screen coords.
- Gravity ay=-G applied once per substep. Thrust F=THRUST*thr*(sin,cos) purely along the nose, no thrust torque. Fuel: fuel=max(0,fuel-MDOT*thr*dt), thrust forced 0 when fuel<=0.
- Steering torque comes ONLY from the tq input; engine gimbal is abstracted as an angular accel term (thr*1.3*tq), NOT a lateral force. Moment of inertia is intentionally baked into TORQUE/gimbal constants (no explicit I). These are intentional arcade simplifications.
- The 'fin'/finD parameter inside stepPhysics is intentionally UNUSED (dead); steering is tq-driven. drawNewGlennBody has its OWN separate finD param (sprite flap) — unrelated, leave alone.
- Flat-plate strake lift is perpendicular to velocity, CL=sin(b)cos(b); the small along-velocity GLIDE_K term (15% of clamped lift, up to ~4 m/s^2) is a KNOWN, documented arcade glide-assist that injects prograde energy on purpose. Do NOT flag GLIDE_K as an energy-conservation bug.
- Bounded VARIABLE substep: steps=min(400,max(1,ceil(dt/(1/120)))), sdt=dt/steps, <=1/120s. NOT a fixed-step accumulator; sub-metre frame-rate drift is expected and fine. Do NOT flag "not fixed step" or small 30-vs-120Hz drift.
- Touchdown gate is velocity+tilt+offset only (no landing-leg/contact geometry, no contact impulse; on success vx=vy=angv=0, y=0 hard-zero). This arcade gate is intentional — do NOT flag "no leg model".
- predictTrajectory intentionally integrates with tq=0 (holds attitude, ignores held steering) — the trajectory X is a "hold what you're doing" read, display-only. Under held steer it can be off 1.4-2.5km BY DESIGN. Do NOT flag the predictor ignoring live steering.
- CoM-pivot: state (x,y) tracks the booster BASE; the CoM is derived and held fixed across the angle update, base re-placed. This is correct, verified.
- The Python ports (scripts/test_physics.py, local/scripts/*.py) use WRONG constants (offline sim carries ~2.5x short) — they are NOT ground truth and are out of scope. Do NOT analyze or compare against them.
- The mars/MK1 autopilot crashing hard in a bot run is a bot-tuning artifact, NOT a game bug.
`;

const FINDING_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'one-line summary' },
          location: { type: 'string', description: 'function name + approx line number(s)' },
          severity: { type: 'string', enum: ['crash', 'logic', 'visual', 'smell'], description: 'crash=throws/NaN; logic=wrong-but-finite result; visual=wrong render but harmless; smell=fragile/confusing but works' },
          category: { type: 'string' },
          description: { type: 'string', description: 'what is wrong' },
          evidence: { type: 'string', description: 'exact code snippet / line the claim rests on' },
          wrong_behavior: { type: 'string', description: 'the observable incorrect behavior a player or dev would see' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
        required: ['title', 'location', 'severity', 'description', 'evidence', 'wrong_behavior', 'confidence'],
      },
    },
  },
  required: ['findings'],
};

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    is_real_bug: { type: 'boolean', description: 'true only if this is a genuine defect that is NOT on the intended-behavior list and NOT already correct' },
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'intended-behavior', 'needs-human'] },
    reasoning: { type: 'string' },
    corrected_severity: { type: 'string', enum: ['crash', 'logic', 'visual', 'smell', 'none'] },
    fix_sketch: { type: 'string', description: 'if confirmed, a one-to-three line sketch of the minimal fix' },
  },
  required: ['is_real_bug', 'verdict', 'reasoning', 'corrected_severity'],
};

// Code regions to analyze. Weighted toward NEVER-audited, high-logic-risk code.
// (Physics core got a 36-agent audit 2 days ago; it gets one lighter fresh pass.)
const REGIONS = [
  {
    key: 'orbital-moon-machine',
    lines: '2049-2660',
    focus: `The DORMANT orbital/lunar machine: moonPosAt, moonVelAt, orbAccel, stepOrbit, orbDragNow, predictDrag, predictOrbit, tliWindow, toOrbitalFrame, toLunarDescentFrame, spawnExplosion/Splash, updateShip, doStaging, updateDiscard, updateOrbital. This code is reachable via the moon mode / ?moon= dev gates and is KNOWN to have incomplete P6 items. Hunt: phase-transition bugs, uninitialized/stale state carried between phases, orbital math sign/frame errors, wrong reseed on frame transitions, references to Earth-EDL phases ('reentry'/'flip'/'land') that should be lunar, division-by-zero in orbital period/aerobrake math, and anything that would throw or produce NaN if a player actually flew these phases.`,
  },
  {
    key: 'update-touchdown-scoring',
    lines: '2661-2760',
    focus: `The main per-frame step loop update() plus evalTouchdown, evalMoonLanding, finish, crash, safeEntrySpeedKmS. Hunt: ground-contact branch selecting the WRONG evaluator for the mode, score formulas that can go negative or NaN, best-score comparison bugs, tier-stat writeback errors, wrong crash-reason selection, phase gating that lets contact fire in the wrong phase, and mismatches between the displayed touchdown numbers and the pass/fail gate.`,
  },
  {
    key: 'scoring-save-tier',
    lines: '814-962',
    focus: `landingSpec, resize, loadSave, persist, tier stats (loadTierStats/saveTierStats/setTier), boardKey, localEntries, submitScore, openBoard. Hunt: per-tier leaderboard key collisions, save-migration bugs (missing fields on old saves -> NaN/undefined), sort order wrong (score ascending vs descending), best-score not persisted, tier switch losing data, localStorage parse with no fallback.`,
  },
  {
    key: 'mode-start-newrun-params',
    lines: '493-792',
    focus: `T/tier params, applyModeParams, inOrbitalPhase, nearMoon, moonStage, deckX. Also newRun at 1626-1757 and startMode/startMoon/seedMoonPhase at 1407-1457. Hunt: a mode that doesn't fully reset state in newRun (stale fields from a prior run), applyModeParams overriding or FAILING to override a constant, deckX returning wrong value per mode/tier, seedMoonPhase seeding Earth-EDL phases for a lunar run (known P6 smell), moonStage mass/thrust wrong.`,
  },
  {
    key: 'hud-guide-numeric',
    lines: '3641-4250',
    focus: `NUMERIC/LOGIC correctness (not pixel aesthetics) of: drawTrajectory, drawEntryGate, drawBurnStop, drawTargetPointer, drawMK1DistanceIndicator, drawReentryGuide, drawGlideGuide, predictHeatTimeout, predictBurnDuration, drawLandingSiteMarker. Hunt: guidance cues that compute the WRONG number (e.g. burn-in countdown sign flipped, heat-timeout horizon math wrong, SHORT/LONG direction inverted vs actual miss sign, deck-side steer arrow pointing the wrong way), division-by-zero when spd or dt is 0, and NaN propagation into hudText. NOTE drawGlideGuide's 3 ctx.restore() are on mutually-exclusive early returns = balanced (already verified) — do NOT flag that.`,
  },
  {
    key: 'physics-predictor-fresh',
    lines: '1758-2049',
    focus: `A FRESH lighter pass on stepPhysics, wind, rho, smoothK, predictTrajectory, predictBurnStop, and the direction helpers. The core was audited 2 days ago (21 classic bug-classes REFUTED — see the intended-behavior list, respect it strictly). ONLY report something NEW that the audit did not cover: e.g. an off-by-one in the substep count, a guard that fails at exactly dt=0 or fuel=0 or spd=0, an edge case in predictBurnStop's vertical-burn assumption that produces a NaN, or a clamp that can be exceeded. Do NOT re-report any refuted/intended item.`,
  },
  {
    key: 'camera-projection-particles',
    lines: '2919-3260',
    focus: `updateCam, moonCamTarget, snapGroundCam, w2sX/w2sY, curveOff, drawSky, lerpColor/h01/rgb, surfacePath, drawClouds, drawLandStrip, drawSeaStrip, drawGround (start). Hunt: camera math that can divide by zero (cam.s=0), NaN in projection when b is null or in a transitional scene, curveOff producing runaway offsets, color lerp with out-of-range t producing invalid rgb() strings, sea/land strip loops that can run unbounded or index out of range.`,
  },
  {
    key: 'input-ui-lifecycle',
    lines: '1160-1425',
    focus: `Input/UI lifecycle: drawChallengeHUD/Banner, holdButton, tapButton, cycleViewMobile, warpStep, positionDot, updateMoonChips, rotateLocked, syncMobileUI, syncWakeLock, hit/hitZones, endBoardDrag, startMode, startMoon. Also handleKeyPress at 6794 and the frame() dispatch at 6873. Hunt: event handlers that reference undefined state before newRun, hitZone leaks, key handling that mutates the const keys map incorrectly (reassign vs delete), warp index out of WARP_STEPS range, mobile/desktop branch that throws when b is null on the menu.`,
  },
];

phase('Find');

// pipeline: each region -> find -> verify each finding (starts as soon as that finder returns)
const perRegion = await pipeline(
  REGIONS,
  (region) => agent(
    `You are an expert JS/Canvas game-code auditor doing an adversarial ERROR-ANALYSIS pass on a single-file HTML5 canvas game (2D New Glenn booster landing game).

Read the file ${FILE} and analyze ONLY lines ${region.lines} (region "${region.key}"). Use the Read tool with offset/limit to read that exact range (plus a little context around it and any helper/constant it references elsewhere — you may read other ranges to resolve a symbol, but only REPORT bugs whose root cause is in your region).

REGION FOCUS: ${region.focus}

${DONT_FLAG}

Report GENUINE defects only: things that throw, produce NaN/Infinity, compute a wrong-but-finite result, render at wrong coordinates, or are logically inconsistent. For each, give the exact code evidence (quote the line) and the observable wrong behavior. Prefer precision over volume — a false finding wastes a verification agent. If the region is clean, return an empty findings array. Be concrete about line numbers.`,
    { label: `find:${region.key}`, phase: 'Find', schema: FINDING_SCHEMA, agentType: 'general-purpose' }
  ).then(res => ({ region: region.key, findings: (res && res.findings) || [] })),

  (found) => {
    const fs = found.findings || [];
    if (!fs.length) return { region: found.region, verified: [] };
    return parallel(fs.map(f => () =>
      // 2 independent skeptics per finding, DIFFERENT lenses, both told to default to refute if unsure.
      parallel([
        () => agent(
          `Adversarial verification (CORRECTNESS lens). A code auditor claims this is a bug in the 2D NG landing game (file ${FILE}). Your job is to REFUTE it unless it is unambiguously real. Read the cited code yourself (Read tool, the lines in the location) and trace the actual behavior.

CLAIM: ${JSON.stringify(f)}

${DONT_FLAG}

Decide: is this a REAL defect, or is it refuted / intended-behavior / already-correct? Default to refuted or intended-behavior if you are not certain the code genuinely misbehaves. If confirmed, sketch the minimal fix.`,
          { label: `verify-c:${found.region}`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'general-purpose' }
        ),
        () => agent(
          `Adversarial verification (INTENDED-BEHAVIOR + REPRODUCIBILITY lens). A code auditor claims this is a bug in the 2D NG landing game (file ${FILE}). Many "bugs" in this codebase are actually documented arcade design choices. Your job: determine whether this claimed bug is (a) on the intended-behavior list, (b) unreachable dead code that cannot affect a player, (c) genuinely reproducible in normal play, or (d) already handled by a guard elsewhere. Read the code AND any guards/callers.

CLAIM: ${JSON.stringify(f)}

${DONT_FLAG}

Return is_real_bug=true ONLY if a player or developer would actually hit this in a reachable code path AND it is not intended behavior. Default to refuted/intended if uncertain.`,
          { label: `verify-i:${found.region}`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'general-purpose' }
        ),
      ]).then(verdicts => {
        const vs = (verdicts || []).filter(Boolean);
        const realVotes = vs.filter(v => v.is_real_bug).length;
        const confirmed = realVotes >= 2 && vs.length === 2; // BOTH skeptics must affirm
        return { finding: f, region: found.region, verdicts: vs, realVotes, confirmed };
      })
    )).then(verified => ({ region: found.region, verified: verified.filter(Boolean) }));
  }
);

phase('Synthesize');

const allVerified = perRegion.flatMap(r => (r.verified || []));
const confirmed = allVerified.filter(v => v.confirmed);
const contested = allVerified.filter(v => !v.confirmed && v.realVotes >= 1);

// Completeness critic: given the confirmed set + the region list, what did we likely MISS?
const critic = await agent(
  `You are a completeness critic for an error-analysis sweep of a single-file 2D canvas game (${FILE}, ~6955 lines, one <script>).

Regions analyzed: ${REGIONS.map(r => r.key + ' (' + r.lines + ')').join(', ')}.
Confirmed bugs so far: ${JSON.stringify(confirmed.map(c => ({ title: c.finding.title, loc: c.finding.location, sev: c.finding.severity })))}.
Contested (1 of 2 skeptics affirmed): ${JSON.stringify(contested.map(c => ({ title: c.finding.title, loc: c.finding.location })))}.

The runtime happy-path (full ascent+descent+touchdown for ocean/tower/mars) is already proven crash-free and NaN-free with balanced canvas state. Static checks (brace balance, dup defs, dangling ALL_CAPS refs) are clean.

What classes of error might this sweep have MISSED? Consider: code regions not in the analyzed list, cross-function state contracts, save-format migration, resize/orientation handling, audio lifecycle, the menu/board/done UI screens, and any 'unknown-unknowns'. Return a short prioritized list of specific follow-up checks worth running, each with WHY.`,
  { label: 'completeness-critic', phase: 'Synthesize', agentType: 'general-purpose' }
);

return {
  summary: {
    regions: REGIONS.length,
    total_findings: allVerified.length,
    confirmed_count: confirmed.length,
    contested_count: contested.length,
  },
  confirmed: confirmed.map(c => ({ ...c.finding, verdicts: c.verdicts })),
  contested: contested.map(c => ({ ...c.finding, realVotes: c.realVotes, verdicts: c.verdicts })),
  completeness_critic: critic,
};
