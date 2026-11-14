# IL cost analysis (offline hook profiler)

Lists the engine calls a mod's hooks make per trigger, from the compiled assembly, without starting the game.

## What it does

`tools/ilcost` reads a compiled mod assembly with Mono.Cecil and finds every hook the game calls by itself: Harmony patch bodies (from the `[HarmonyPatch]` attributes), Unity message methods of `MonoBehaviour` types, network receivers and coroutine steps. For each hook it walks the IL of the hook and of everything it calls inside the analysed assemblies (default `CasualtiesMP`, `Assembly-CSharp`, `CUCoreLib`) and counts the call sites by category: `GetComponentInParent`, `GetComponent`, `GetComponents*`, `SceneScan` (`FindObjectsOfType` and friends), `Physics`, `TransformWalk`, `UnityNullCheck`, `Lifecycle`, `LINQ`, `String`, `Log`, `Reflection`, `Alloc`, `UnityOther`.

Two numbers per hook:

- Cheapest path: the sites along the lowest cost route from entry to a return, under the stated assumptions. This is the route a hook takes when its early outs fire.
- Upper bound: every site on any live path, loops counted once. It overstates, because branches that exclude each other are all counted.

The real cost per call lies between the two. Call counts are exact statements about the IL. Nanosecond figures use a unit cost per category (`Rules.EstimatedNanoseconds`) that is a guess from general knowledge of the engine, not a measurement. Every nanosecond figure is an ESTIMATE; `GetComponentInParent` is scaled by `--hierarchy-depth` (default 4 levels) and `SceneScan` by `--scene-objects` (default 5000).

## Assumptions

A flag that is off prunes its own branches:

- `--assume-field Type.field=true|false`: a static bool read right before a branch.
- `--assume-return Type.Method=true|false`: a method returning bool read right before a branch.
- `--assume-null-field Type.field`: a static reference field that holds null in the analysed state.
- `--assume-live-objects`: a null test on a reference or Unity object finds a live object (the happy path), except for the null fields above.
- A literal `null` passed to a callee, or forwarded from a parameter already known to be null, is followed into the callee.

`tools/ilcost/dev_off.args` holds the set for the Telekinesis dev feature off with nothing loaned. Those assumptions come from reading the source of `Telekinesis.cs`; they are not checked by the tool.

## Run

```
dotnet build tools/ilcost -c Release
tools/ilcost/run_ilcost.sh <stage>/plugins/Together $(cat tools/ilcost/dev_off.args) --compare-with <older>/CasualtiesMP.dll --md out.md --json out.json
```

`--filter <regex>` limits the hooks by name or patch target, `--explain` prints the costed sites on the cheapest path, `--collisions-per-second`, `--fps` and `--tick-hz` set the trigger rates used for the share of one core. The build reads `Mono.Cecil.dll` from `BepInEx/core` of the installed game (`-p:CecilDll=` overrides) and the run reads game assemblies from the installed `Managed` folder. Nothing is written there and the game is not started.

## What it can and cannot prove

Can: which engine calls a hook makes, how many per trigger on a path, that a source change removed or added a call (compare two assemblies), that a guard takes a path off the hot route.

Cannot: native engine cost (the unit costs are guesses), loop iteration counts, how often a trigger fires in a real session, branches decided by runtime data other than the assumptions, virtual and delegate calls (not followed), time spent outside the hooks. A mock engine micro benchmark was not built: the real hook bodies call native Unity objects, so running them needs either the engine or a stub assembly of every game type they touch (Body, Limb, Con and the rest), and a stub would measure the stub.

## Tests

`dotnet run -c Release --project tools/ilcost-tests` runs 11 tests against a fixture assembly with known call counts, including: identical inputs give identical rows, one added call changes the estimate by exactly its unit cost, a comparison lists the changed hook. Each analyzer rule was mutation checked by hand (branch resolution, loop detection, callee following, path cost, dead edges): every mutant fails a test.
