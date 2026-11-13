# Architecture

The repository has four top-level folders and one folder of documents. Each has one job.

```
plugin/         CasualtiesLink: the C# BepInEx plugin that runs inside the game
plugin-tests/   offline tests of the plugin code that does not need Unity
client/         everything Python that talks to the plugin or starts games
tools/          command line programs for the operator, plus the commit message check
docs/           this file and the topic documents
.githooks/      commit-msg hook (calls tools/check_commit_message.py)
```

## client/

```
client/
  casualtieslink/     the library
    (top level)         link client: parsing, transport, commands, cli, launcher, lock, observe
    games/              game copies and pairs: testcopy, pair, instances, friendszip, recovery, udpproxy
    scenarioengine/     how a scenario runs: desync, launchplan, positioncontrol, swinggate
    charselect/         the paged character select check: pagedselect, pagedverify, oswindow
    reports/            readers of saved reports and logs: launchsummary, miningsummary, pr24log, prtable
  scenarios/          scenario definitions that run on two games (data and checks, no runner)
  live/               unittest modules that need a running game
  unit/               unittest modules that never start a game (fixtures/ holds report files copied from real runs)
  profiles/           PR result table profiles read by tools/pr_table.py
  run_tests.py        the single entry point for both kinds of test
  change_selection.py decides which test modules need to run (used by run_tests.py)
  test_groups.json    the list of test groups run_tests.py knows
```

### Dependency direction

`live/` and `scenarios/` import `casualtieslink`. `unit/` imports all three. `casualtieslink` imports none of them. Inside the library the order is: the top level imports nothing from the subpackages, `games/` imports the top level, and `scenarioengine/`, `charselect/` and `reports/` may import `games/` and the top level. `tools/` imports `casualtieslink`.

### What each library module does

| Module | Job |
|---|---|
| `parsing` | decode replies and `key=value` arguments, find a command in `/describe` output |
| `transport` | HTTP to one game, one port per game |
| `commands` | `Game`, one method per link command |
| `cli` | `python -m casualtieslink` |
| `launcher` | start and stop one game process, build the `--mp-*` arguments |
| `lock` | the machine-wide game lock file, the marker that someone is using the game |
| `observe` | read facts out of logs and plugin state for the gate scenarios |
| `games.testcopy` | copy the game folder (never inside this repository) |
| `games.pair` | host and client games, profile snapshot and restore |
| `games.instances` | install a plugin set into a game copy, the build and stage table, `ScenarioGames` |
| `games.friendszip` | unpack and verify the friends zip |
| `games.recovery` | clean up after an aborted run |
| `games.udpproxy` | delay, jitter, loss and reorder between host and client |
| `scenarioengine.desync` | `Scenario`, `SeriesScenario`, observation, verdicts, reports, launch log checks |
| `scenarioengine.launchplan` | group scenario runs into game launches |
| `scenarioengine.positioncontrol` | hold bodies at exact places and prove they stay |
| `scenarioengine.swinggate` | gate every counted swing on fresh reads, settle the limbs, classify a run as valid, invalid or fail |
| `charselect.*` | build a test character pack, drive the select screen with real OS input |
| `reports.*` | summarise saved reports and host logs; `reports.prtable` builds the PR result tables from a profile |

## Where new things go

### A new scenario (two games, one action, one verdict)

1. Add a module `client/scenarios/<what_it_checks>.py` with a `GROUP` constant and a list `SCENARIOS` of `Scenario` objects (`SeriesScenario` for a scenario that runs once per network profile). End the module with `base.SCENARIOS.extend(SCENARIOS)`, where `base` is `scenarios.desync_scenarios`.
2. Import the module at the end of `client/scenarios/world_building.py` (or, for a module that only adds to `SERIES_SCENARIOS` like `wood_mining`, at the end of `desync_scenarios.py`). A scenario is only known to the runner once something imports its module.
3. Add `client/unit/test_<same name>.py`. It runs the scenario against `unit/fake_link.py` and checks the verdict logic, the report fields and the planned gates. Offline tests are required; the live behaviour is checked by running the scenario.
4. Run it with `python client/run_tests.py --pair --only desync --together <build> --match <name>`. The scenario groups and the options are in `docs/SCENARIOS.md`.

Library code a scenario needs (an observation, a parser, a hold) goes in `casualtieslink/`, not in the scenario module, once a second scenario uses it.

### A new link command

1. In `plugin/`, add `Add("name", "what it does", args => ...)` in the `Register*` method of the `Commands*.cs` file that owns the area (`Core`, `Run`, `World`, `Reflection`, `Bodies`, `Net`). Logic that does not need Unity goes in its own class so `plugin-tests/` can compile and test it.
2. In `client/casualtieslink/commands.py`, add a `Game` method if scripts will call it often. `Game.call("name", ...)` works for any command without it.
3. Add a test: a plugin test for Unity-free logic, a `live/` test for the game side, and a `unit/test_client_fake.py` case for the client method.
4. Update the command table in `docs/PROTOCOL.md`. `GET /describe` is the exact list; the table is the map.

### A new live test of the game itself

A `unittest` module `client/live/test_<area>.py` using `live.shared_game` for the shared game. Add it to a group in `client/test_groups.json`. A module that starts its own game process without a copy belongs in a group flagged `uses_installed_game`; a unit test enforces that.

### A new operator program

`tools/<verb_noun>.py`, a thin command line over a library function. Parsing and logic live in `casualtieslink/`, the file in `tools/` only reads arguments and prints. A test for the logic goes in `client/unit/`. Add it to the table below.

### The programs in tools/

| Program | Job | Documented in |
|---|---|---|
| `check_commit_message.py` | the commit-msg hook check | README |
| `desync_summary.py`, `mining_summary.py`, `pr24_summary.py` | sum the reports of one launch or one mining series | `SCENARIOS.md` |
| `wood_mining_table.py` | result table of the wood mining launches | `SCENARIOS.md` |
| `pr_table.py` | compact PR result tables from a profile in `client/profiles/` | `TESTING.md` |
| `package_log_check.py` | check the BepInEx logs of one launch of a friend package | `SCENARIOS.md` |
| `paged_select.py`, `paged_select_verify.py` | run and verify the paged character select check | `SCENARIOS.md` |
| `recover_after_abort.py` | stop stray games, restore the profile, delete scenario copies and a stale lock | `SCENARIOS.md` |
| `steam_selfjoin.py` | Steam self-join experiment on two harness copies | `SCENARIOS.md` |
| `mutation_check.py` | break the code on purpose and run the offline tests | `TESTING.md` |
| `gate_mutation_check.py`, `proxy_mutation_check.py`, `prtable_mutation_check.py` | the same for the swing gate, the proxy stall mode and the PR tables | `SCENARIOS.md`, `TESTING.md` |

## How tests are organised and run

| Kind | Where | Starts a game | Run with |
|---|---|---|---|
| Python offline | `client/unit/`, `tools/test_*.py` | no | `python client/run_tests.py --offline` |
| Plugin offline | `plugin-tests/` | no | `python client/run_tests.py --offline` (also part of it), or `dotnet run -c Release --project plugin-tests` |
| Live, one game | `client/live/` groups `link`, `run`, `world`, `inert` | yes, installed folder | `python client/run_tests.py --only link run world --allow-installed-launch` |
| Live, two games | `client/live/` groups `pair`, `gates`, `friends-zip`, `desync` | yes, own copies | `python client/run_tests.py --pair --only <group>` |

`run_tests.py` only reruns modules whose files changed since they last passed. `--all` forces everything. Details are in `docs/TESTING.md`.

Unit test files are named after the module they cover: `unit/test_<module>.py`. A test for a scenario module is `unit/test_<scenario module>.py`.

## Rules

- Names say what a thing is. No `helper`, `data`, `v2`, `new`, `final` and no single letters outside short loops.
- Comments state intent, a constraint or a trap. The code is the description of what it does.
- Paths derive from the file's location or from an environment variable with a documented default. Nothing absolute and nothing personal is committed.
- Docs describe the system as it is. History is in git.
- No behaviour change in a commit that moves or renames files.
