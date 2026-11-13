# Running and organising the tests

The one entry point is `client/run_tests.py`, run from any folder. Offline tests first: they never start a game, and `--offline` also runs the plugin tests in `plugin-tests/`.

## Offline tests

Most of the suite runs without the game. Start there:

```bash
python client/run_tests.py --offline            # never starts the game; about 5 seconds the first time, nothing when nothing changed
python client/run_tests.py --offline --list     # what would run, and which changed file caused it
python client/run_tests.py --offline --failfast
```

The game tests need a free machine, because the game is single instance and the runner takes the machine-wide game lock. The groups `inert`, `link`, `run` and `world` start the game from the installed folder, so a run without flags refuses to start them: when the change selection picks one of them the runner prints the flags below and exits with code 2 before it locks, snapshots or starts anything. `--list` and `--offline` never refuse. `--allow-installed-launch` is the explicit permission; with it the runner snapshots the profile folder and the PlayerPrefs registry key first (the `start_run` command sets `didbasiccourse`) and restores both after the games have closed, also when a test raises. The groups that start their own copies (`pair`, `gates`, `desync`) are not refused and still need `--pair` or `--builds`.

```bash
python client/run_tests.py                       # offline groups that changed; refuses, listing the flags, if a single-game group is selected
python client/run_tests.py --all --allow-installed-launch   # everything, starting the installed game for link, run, world and inert
python client/run_tests.py --only world --allow-installed-launch
python client/run_tests.py --attach              # use a game that is already running with the link; starts nothing
python client/run_tests.py --pair                # also run the host and client tests (own copies)
python client/run_tests.py --pair --only pair --budget-seconds 900
python client/run_tests.py --pair --only pair --match visuals
python client/run_tests.py --mutate corrupt-save --only world --allow-installed-launch
python client/run_tests.py --mutate no-dune --pair --only pair
```

### What reruns

`run_tests.py` works out, for each test module, which files it depends on: the module itself, every module of this repository that it imports (found by reading the imports, so nothing has to be listed by hand), and for the game groups the plugin sources. It stores a hash of each of those files when the module passes. The next run only runs the modules where a hash differs, and `--list` names the file. Examples: changing `casualtieslink/games/pair.py` runs `unit.test_pair_fake` and nothing else; changing a plugin file reruns the game groups and not the offline ones; changing line endings alone reruns nothing. A module that failed runs again until it passes, and a module that was only skipped is not recorded as passed. State lives in `client/.test_state.json`.

`test_groups.json` lists the groups. A module is either a Python test module or a command with its own watch list (the plugin tests). `needs_game` groups share one game that the runner starts and closes. `owns_game` groups (`inert`, `pair`) start their own games and run first. A group with `uses_installed_game` (`inert`, `link`, `run`, `world`) starts the game from the installed folder and is refused without `--allow-installed-launch`; a unit test fails when a test module starts a game process without a copy and is not in such a group. `--match` runs only tests whose id contains the text, `--budget-seconds` fails the run when it takes longer, and the summary shows the total time and any module slower than five seconds.

### The groups

| Group | Needs the game | What it checks |
|---|---|---|
| link | yes | status, self description, unknown command, missing argument, missing header, `Origin` and `Host` refusals, `describe_type` |
| run | yes | each character spawns the right player object, starting outside the menu fails, quitting to the menu sends `scene_changed` |
| world | yes | spawn and pickup, the bandage minigame starts, damage with events and bleeding, console round trip and `heal`, writing then reading a field, stepping frames, injected keys move the player, a screenshot is a PNG, the pickup event, save and load |
| inert | yes, its own | without the switch the port is closed, nothing listens, the DISABLED line is logged and no config file appears; with `--link-port` it answers and logs ENABLED |
| pair | yes, its own two | a Dune host and client: both see both players, the handshake is accepted, every body is `charType` 2 with skills 17/18/0 and gain multipliers 1/1/0.5 on both games, injuries are not damped by default, and with the DuneHardy rule switched on (`--mp-setrule DuneHardy 1`) pain gain is 0.7 and bleeding gain 0.8, a stock 5.4.0 client is refused with "Version mismatch"; mixed characters in both directions; remote bodies look like the local body of that character; a pointing arm has the same angle on the other game |
| client-offline | no | reply and argument parsing, `--mp` flags, the change selection, the game lock, the test copy, the transport and `Game` against a fake game server, the command line, the launcher with a fake process (refuses a second game, command line, save backup and restore, kill on timeout), `ProfileGuard` and `GamePair` with fakes (start order, cleanup after a failed client, restoring the profile) |
| repo-tools | no | the commit message check |
| gates | yes, its own two | the scenarios A to D above |
| desync | yes, its own two | a client does something and the host may revert it: see the next section |
| plugin-offline | no | `plugin-tests/`, a console program that compiles the Unity-free parts of the plugin and checks them: the launch switch, the key press windows (down, held and up frames), the request gate (host, `Origin`, header, method and path rules), the reflection path parser and the event buffer (numbering, filters, capacity, waiting reads, many threads) |

The fake game server is `client/unit/fake_link.py`. It speaks the same protocol (envelope, header, `/describe`, `/events`) from a local port, so the client, the command line and the launcher are tested without Unity.

The parts of the plugin that need Unity (the reflection walker, the commands, Harmony patches) can only be checked with the game, in the `link`, `run` and `world` groups.


## Result tables for a PR

`python tools/pr_table.py client/profiles/corpse-fix.json` prints the compact result of one PR or topic: a header line (topic, game version, the parameters that define the test), the builds with a shortened identity, then a MAIN block and a REGRESSION block, each with its own tables and its own verdict line, and below them only the deviations (a run invalid, FAIL, confounded, excluded for a slow swing rate, or fewer runs than planned, each with a reason of a few words). Every number is computed from the report JSONs under `.state/`. MAIN holds the tests that prove what the PR changes, REGRESSION the tests that prove existing behaviour still holds. `--format fenced` wraps the aligned text in a fenced code block of type text for a PR comment, `--format markdown` gives GitHub-flavoured Markdown for a PR body (`### Main tests`, `### Regression tests`, pipe tables, `|`, `<` and `>` escaped, ASCII only, LF, no HTML), `--format both` prints text and Markdown; `--root` moves the directory the profile's source patterns are relative to.

A profile (`client/profiles/*.json`) is the data that decides what a PR shows: `sources` (report globs), `params` (`real_rate_median_max` excludes runs whose median swing interval is above it), `superseded_confounders` (confounded causes that no longer count), `header` fields, `builds` (an optional `stageDll` whose md5 prefix identifies the build, otherwise the reports' `dllSha256` prefix), and `tables`. Every test row has a `role`, MAIN or REGRESSION, in the profile and not in the scenario code: the same scenario can be MAIN in one profile and REGRESSION in another, and a profile with an unlabelled test is refused. A `pair_rows` table has one row per scenario and build with the columns `host_hp`, `client_min` and `broke` (host and client copy health, with `->gone` when the copy became unreadable, and the swing at which it did). A `metric_rows` table has one row per metric and one column per build: `swings_landed` and `verdict_count` show valid runs over executed runs, and `attack_hook` shows the Body.Attack transpiler count of the launch checks. A swing test is all or nothing (see "All or nothing swings" in SCENARIOS.md): a run counts as valid only when every swing landed; a run with a missed swing and every gate recorded as passed is a FAIL, one without a gate record is invalid ("swing missed", with the cause the row's `miss_cause` names when it explains every miss), and runs marked INVALID, NOT COUNTED or CONFOUNDED never enter a count. A row can carry `expect` (`{"fix": "all"}` for a metric, `{"PR24+fix": {"broke": "sw11"}}` for a pair) and the block verdict is FAIL when a valid run does not meet it; otherwise it reads "all n valid runs as expected" with the invalid, excluded and not-run counts. A cell with no run prints `-`. A build entry in a `metric_rows` table can carry its own `sources`, so two columns can show two launches of the same build, and a row can carry a `note`, a line listed under the tables for something no report shows (for example a setup that failed before any report was written). The profile's `reasons` list maps issue text to the short reason shown for an invalid run.

| Test | `corpse-fix` profile | `hit-fix` profile |
|---|---|---|
| `corpse_chain_by_client`, `corpse_chain_dune_dune_by_client`, `corpse_chain_milky_milky_by_client`, `corpse_chain_dune_milky_by_client` | MAIN | not used |
| `pvp_banded_by_client`, `spawned_crate_hit_by_client`, `staticcrate_hit_by_client`, `v2check_dig_cracks`, Body.Attack startup lines | REGRESSION | MAIN |

`client/profiles/corpse-fix.json` and `client/profiles/hit-fix.json` are the two shipped profiles. The code is `casualtieslink/reports/prtable.py`; `unit/test_prtable.py` runs it against fixtures copied from real reports in `unit/fixtures/prtable/`, checks the Markdown rules and a golden file, renders the Markdown with python-markdown and markdown-it-py when they are installed (GitHub's own renderer, cmark-gfm, is not used, so this shows the tables parse, not that GitHub renders them), and `python tools/prtable_mutation_check.py` fails when a mutation of the tool is not caught.

## Checking that the tests can fail

`tools/mutation_check.py` breaks the code on purpose in scratch copies, one change at a time (the list is `tools/mutants.json`), runs the offline tests against each copy and reports any change they did not notice. For example a second game being allowed, the save backup left behind, the plugin accepting an empty `Origin`, a held key one frame short.

```bash
python tools/mutation_check.py                  # all mutants, about 4 minutes
python tools/mutation_check.py --suite plugin   # only the plugin tests
python tools/mutation_check.py --match Origin
```

`--mutate` breaks the running game setup instead. `corrupt-save` truncates the save before loading, and the save and load test fails. `no-dune` leaves out `--mp-setchar 2`, and five Dune checks fail (`charType` 0 instead of 2, skills 9/8/7 instead of 17/18/0, no pain damping).

The stock client test needs `CU_STOCK_TOGETHER_DLL` to point at a stock 5.4.0 `CasualtiesMP.dll`, otherwise it is skipped.

Not covered: bandaging a limb from start to finish (only the start of the minigame is checked), a saved world beyond one field, fullscreen and focus behaviour, and Steam lobbies (the pair uses direct IP with `--mp-nosteam`).
