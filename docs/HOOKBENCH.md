# Hook benchmark

Status: one live run done (2026-11-14, `--mode host`, stage upstream-full-release-e9eb3ce, hooked pass only, 150 s). Modes: `host` and `pair` work (the world starts through the multiplayer host flags and `ready_up`); `solo` (no multiplayer flags, `start_run` from the menu) is UNSUPPORTED: in two launches the world did not load within 60 s and the main thread then stopped answering, and the cause was not diagnosed because the logs were lost. The runner now keeps the BepInEx log of each copy under `<out>/<label>/logs` before the copy is deleted (`tools/hookbench_logs.py`, tested by `tools/test_hookbench_logs.py`).

Measures what a mod's engine-called code costs, from inside the game, and decides whether two builds differ.

## Parts

| Part | What it is |
|---|---|
| `plugin-hookprofiler/` | BepInEx plugin (build: `dotnet build plugin-hookprofiler -c Release`). Finds every Harmony patch body, Unity message method (`Update`, `FixedUpdate`, `LateUpdate`, `OnGUI`, `OnCollision*`, `OnTrigger*`), network receiver and coroutine step of a mod assembly, and wraps each in a Stopwatch pair. |
| `tools/hookbench.py` | Launches a harness game copy with the plugin, builds a seeded scene, records a clean pass and a wrapped pass, saves JSON per launch, compares two report folders. |
| `tools/hookbench_stats.py` | Noise floor per metric and the verdict `no difference` / `candidate slower` / `candidate faster`. |
| `tools/hook_diff.py` | Static list of hook entry points a commit range adds or removes. Suspects only; the runtime inventory is the ground truth. |

## What the plugin measures

Driven through the link: `invoke` on `static:HookProfiler.Control` with string arguments.

- `Setup(disable, uncap)`: removes the Harmony patches whose declaring type name contains a fragment of `disable` (the removal variant, no rebuild), and with `uncap` = `1` turns vsync and the frame cap off so frame time measures work. Adds the per frame recorder.
- `Wrap(assemblies, burn)`: wraps every hook. `burn` is `fragment:microseconds,...`, a deliberate busy loop inside the matching hooks, used to show the benchmark can fail. Calibrates the wrapper itself (empty method, 2 million calls) and reports it as `overheadNsPerCall`.
- `Begin(label)` and `End()`: reset, record, return JSON: frame time mean, p50, p95, p99, max; hook time per frame; fixed tick count; process CPU share of one core; GC collections; per hook calls, total ms, top level ms (outermost hooks only, so nested hooks are not counted twice), mean, net mean (wrapper overhead removed), p95 and p99 (power of two histogram, so a factor of two resolution), max, calls per frame, calls per fixed tick.
- `Inventory(assemblies)`: every hook with kinds, patch targets and an IL hash, so two builds can be diffed for added and changed hooks.

Limits: hooks run on threads other than the main thread are skipped; hook cost is inclusive of nested hooks; the timer tick is 100 ns, so one call under a microsecond is dominated by quantisation and only the sum over many calls is meaningful.

## Method

A launch records two passes in the same world. The clean pass wraps nothing, so frame time and CPU are free of wrapper cost. The wrapped pass gives per hook numbers. Each pass spawns the same seeded scene (default 8 bodies and 24 crates dropped in a column), waits 5 s, records 30 s, and removes the scene.

Noise floor first: run the same build several times (`--repeat 5` or more) and read `baselineNoise`. A difference is reported only when the gap between run means is larger than 3 standard errors of the difference and larger than 2 % of the baseline mean (`hookbench_stats.compare`).

Proving the benchmark can fail: run one build with `--burn <hook fragment>:<microseconds>` and compare against the unburned runs; the burned hook must show a per hook total near calls times the burn, and the frame metrics must move when the burn is large enough. Run the same build twice under two labels and compare; the verdict must be `no difference`.

## Prerequisites and safety

The game copies share the profile folder and PlayerPrefs registry with the installed game, and the harness restores a snapshot of both at the end of a run. Close the installed game before any launch. Do not run other game instances during a measurement.

## Tests

- `python tools/test_hookbench_stats.py` (comparison rules, 8 tests, mutation checked by hand).
- `dotnet run -c Release --project plugin-tests` (includes `HookStatsTests`, the counting core).
- The runner and the plugin's Harmony wrapping are exercised only by a real launch.

## Chunk sleep correctness and multiplayer perf

- `tools/chunksleep_ab.py --build <id> --label <name>`: launches host plus one client, holds them 6 chunks apart, spawns labelled crate groups at chunk centres, and samples the awake and asleep state of every watched object on BOTH machines after each move (client to host area and back, host to client area and back, a SimKeep armed on a far crate). Each move also records a fast `SleepProbe.Pulse` trace (hot objects that are still switched off) so the wake latency is measured. `--compare a.json b.json ...` prints per machine counts, the hot-but-off invariant, wake latency, and labelled differences against the first report. The world seed is not controllable, so only the labelled crates are compared across builds.
- A build that wrongly skips a chunk keeps the final states (the mod's `Visit` cycle still wakes everything within about 0.6 s), so the final-state compare cannot fail on it; the wake latency can. Prove the check against a deliberately broken variant before trusting a fix.
- `tools/hookbench.py --mode pair --client-away-chunks 6` holds the client away from the host and profiles both processes in the same passes (`wrapped.client` in the report). `tools/hookbench_side_by_side.py label=report.json ...` prints frame time and per-frame hook cost side by side.
- `plugin-hookprofiler/SleepProbe.cs` (static `HookProfiler.SleepProbe` through the link): `Dump`, `Pulse`, `LocalPosition`, `ChunkKeyAt`, `ArmKeep`. It reads the mod's chunk sleep list by reflection, so it works against any build of the mod.
