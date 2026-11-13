# CU TA Harness

Test automation (TA) for the Steam game Casualties: Unknown. A small BepInEx plugin, CasualtiesLink, runs inside the game and answers HTTP requests on the local machine. A Python client (standard library only) starts the game, sends it commands and runs the tests.

Repository: https://github.com/Sharkmare/CU-TA-Harness

The multiplayer tests use the Together mod: https://github.com/Sharkmare/casualties-together

```
plugin/        CasualtiesLink, C# (netstandard2.1, BepInEx 5, Harmony)
plugin-tests/  offline tests of the plugin's Unity-free code (console program, .NET 9)
client/        the casualtieslink package, run_tests.py, tests/ (need the game), unit/ (no game)
tools/         check_commit_message.py (used by .githooks/commit-msg), mutation_check.py
```

## Build and install

```bash
dotnet build plugin -c Release
cp plugin/bin/CasualtiesLink.dll "C:/Program Files (x86)/Steam/steamapps/common/Casualties Unknown/BepInEx/plugins/CasualtiesLink/"
```

Close the game before copying. The project reads the game's `Managed` folder and `BepInEx/core`; point it at another install with `-p:GameDir=...`. A good start writes `CasualtiesLink ENABLED on port N` to `BepInEx/LogOutput.log`.

## Off unless you ask for it

The plugin does nothing by default. It opens a port only when the game is started with `--link-port N`, or with the environment variable `CASUALTIES_LINK_PORT` set. There is no config file, so copying the game folder to another machine does not turn it on. When it is off it opens no socket, makes no objects, patches nothing, writes no files and costs nothing per frame. It writes one log line, `CasualtiesLink DISABLED (...)`.

The client adds `--link-port` for you. Leave `BepInEx/plugins/CasualtiesLink/` out of any game folder you give to someone else. Nothing else needs it, and the Together mod does not use it.

## Security

- The server listens on `127.0.0.1` only.
- A POST must carry the header `X-CasualtiesLink`. A web page cannot add that header without a CORS preflight, and the server never answers one. Requests with an `Origin` header are refused. The `Host` header must be `127.0.0.1:<port>` or `localhost:<port>`.
- There is no endpoint that calls methods, evaluates code or reads files. `console` runs the game's own console commands, which include cheats, and `get`/`set` change fields by path. Anything that can reach the port can change the game, so do not forward it.

## Protocol

- `POST /cmd/<name>` takes a JSON object and returns `{"ok":true,"result":...}` or `{"ok":false,"error":"...","kind":"..."}`. Status codes: 404 unknown command, 400 the command failed, 403 refused, 504 the game did not answer.
- `GET /describe` lists every command with its arguments, plus the version and protocol number. The table below is only a map; `/describe` is exact.
- `GET /events?since=N&wait=ms&type=T&limit=N` returns events newer than N and waits up to `wait` milliseconds for one.
- Every command that touches the game runs on Unity's main thread, because the Unity API is not thread safe. `start_run`, `load`, `quit_to_menu`, `step`, `screenshot` and `wait_state` finish on a later frame and keep the request open until they do.

| Group | Commands |
|---|---|
| Status | `status`, `state` (menu, pre-run, in-world, loading), `describe_type` |
| Runs | `start_run` (character 0 Experiment, 1 Milky, 2 Dune, plus preset and settings), `wait_state`, `quit_to_menu`, `save`, `has_save`, `load`, `quit` |
| Console | `console`, `console_log`, `game_commands`, `close_console` |
| World | `spawn`, `list_items`, `player`, `damage`, `use_item_on_limb` |
| Bodies | `bodies`, `body_visuals` (sprite names, limb children and angles, arm animator angle, animator controller names) |
| Holds | `hold_body` (hold a Body at an exact x, y), `release_body` (one body or all), `hold_status` |
| Input | `keybinds`, `input`, `mouse`, `input_probe`, `release_input` |
| Time and view | `timescale`, `step`, `screenshot`, `log` |
| Reflection | `find`, `get`, `set`, `invoke` (calls a method by name; `types` picks an overload, for example `["Vector2Int","UInt16"]`) |

`get` and `set` take a target (`player`, `camera`, `world`, `console`, `static:Type`, `type:Type[#n]`, `name:GameObject`, or `id:N` from a handle in an earlier reply) and a dotted path with `[index]` steps, for example `limbs[3].bleedAmount`, or `main.currentMinigame` on `static:MinigameBase`. Values are converted to the field's type: enums by name, vectors as `{x,y}`, object references as `id:N`. Pass `nonpublic:true` to reach non public members.

`hold_body` takes `id` or `local`, `x`, `y` and a `tolerance` (0.001 to 5, default 0.05). A held body is put back at the target on every physics tick and before every frame is drawn, and every velocity under the body is zeroed, so it cannot drift, be pushed or fall off a ledge. `hold_status` reports, per hold, the target, the current position, the drift now, the largest drift seen before a correction, how many ticks exceeded the tolerance and whether the body is still found; `heldWithinTolerance` is true only after at least one tick with none over the tolerance. A hold on a body only acts on the game that holds it, so hold each player on its own machine. `casualtieslink/positioncontrol.py` wraps it: `place_and_hold` seats a body and proves it stays, `seat_pair` holds the attacking client at its seat and parks the other player 12 units away (a seat that fails its verification is released and tried again, up to 3 attempts; `seatAttempts` and `earlierAttemptIssues` are in the report), `preflight_pair` checks both bodies are at their targets within the tolerance and at least 2.0 apart, and `start_positions` records both bodies at the start of a run.

Events: `link_started`, `scene_changed`, `player_ready`, `console`, `item_picked_up`, `damage` (a limb lost health, found by checking every frame), `death`, `exception` (a Unity error or exception).

Key and mouse input works by patching `Input.GetKey`, `GetKeyDown`, `GetKeyUp`, `GetMouseButton(Down)` and `mousePosition`. A key sent on frame F is held on frames F+1 to F+n, so the game never misses the first frame. The real keyboard still works.

## What the game does that the tests have to work around

- With the Together mod active the game refuses singleplayer, so `start_run` stays at the menu. `run_tests.py` starts the game with `--mp-disable`.
- Any cheat command opens the console window, and an open console blocks player input. `console` closes it again unless you pass `keep_open`. The Together mod can also leave the console open on the host at start, so the pair tests call `close_console` first.
- The game sets `Time.timeScale` itself in several places, so pausing with `timescale 0` does not last. `step` puts back whatever it found.
- `start_run` sets the `didbasiccourse` PlayerPref, otherwise a tutorial warning stops the run from starting. The reply tells you the old value.
- The player object is named `Experiment(Clone)`, `Milky(Clone)` or `Dune(Clone)`.
- A second `CasualtiesUnknown.exe` started from the installed folder quits after about a second. One started from a copy of the folder runs.

## Client

```bash
cd client
python -m casualtieslink status
python -m casualtieslink describe [command]
python -m casualtieslink call spawn id=bandage
python -m casualtieslink call get target=player path=limbs[3].bleedAmount
python -m casualtieslink events --since 0 --wait-ms 5000 --type damage
python -m casualtieslink --port 7650 launch --mp starthost immidiate-start setname=Alice ip-port=127.0.0.1:7790
```

Modules: `parsing` (replies and arguments), `transport` (HTTP, one port per game), `commands` (`Game`, one method per command), `launcher` (`GameProcess`, `mp_arguments`), `lock` (`GameLock`), `testcopy`, `pair` (`GamePair`, `ProfileGuard`) and `cli`. The `--mp-*` flag names come from the Together repo linked at the top.

`GameProcess.start()` refuses to start while a `CasualtiesUnknown.exe` is running, because starting a second copy of an online game loses the match. It copies `save.sv` aside before the tests and puts it back afterwards, or deletes the test save if there was none.

`CU-TA-Harness.game.lock` in the system temporary directory marks that someone is using the game. It is one file for the whole machine, so a second checkout or worktree is refused too; the game link ports are machine-wide. Set `CU_GAME_LOCK` to use another path. `GameLock` creates the file exclusively and only removes a lock it made itself. Do not start the game while the file exists.

## Two games at once (host and client)

`GamePair` starts the host from the installed folder (link port 7650) and the client from a copy of that folder (link port 7651). `testcopy.make_copy` makes the copy in `%TEMP%\CU-test-client`, or in the folder named by `CU_TEST_COPY_DIR`, refuses to put it inside this repository, and `GamePair` deletes it afterwards. Both games get `--mp-nosteam` and connect by IP address. The installed folder is never changed.

The two games share one profile: the `LocalLow\Orsoniks\CasualtiesUnknown` folder and the PlayerPrefs registry key. Unity has no per game profile, so `ProfileGuard` copies the folder and the registry key aside before the run and restores them afterwards. The tests do not save during a pair run. Each game writes its own `BepInEx/TogetherLogs/together.log`.

## Tests

Most of the suite runs without the game. Start there:

```bash
cd client
python run_tests.py --offline            # never starts the game; about 5 seconds the first time, nothing when nothing changed
python run_tests.py --offline --list     # what would run, and which changed file caused it
python run_tests.py --offline --failfast
```

The game tests need a free machine, because the game is single instance and the runner takes the machine-wide game lock. The groups `inert`, `link`, `run` and `world` start the game from the installed folder, so a run without flags refuses to start them: when the change selection picks one of them the runner prints the flags below and exits with code 2 before it locks, snapshots or starts anything. `--list` and `--offline` never refuse. `--allow-installed-launch` is the explicit permission; with it the runner snapshots the profile folder and the PlayerPrefs registry key first (the `start_run` command sets `didbasiccourse`) and restores both after the games have closed, also when a test raises. The groups that start their own copies (`pair`, `gates`, `desync`) are not refused and still need `--pair` or `--builds`.

```bash
python run_tests.py                       # offline groups that changed; refuses, listing the flags, if a single-game group is selected
python run_tests.py --all --allow-installed-launch   # everything, starting the installed game for link, run, world and inert
python run_tests.py --only world --allow-installed-launch
python run_tests.py --attach              # use a game that is already running with the link; starts nothing
python run_tests.py --pair                # also run the host and client tests (own copies)
python run_tests.py --pair --only pair --budget-seconds 900
python run_tests.py --pair --only pair --match visuals
python run_tests.py --mutate corrupt-save --only world --allow-installed-launch
python run_tests.py --mutate no-dune --pair --only pair
```

### What reruns

`run_tests.py` works out, for each test module, which files it depends on: the module itself, every module of this repository that it imports (found by reading the imports, so nothing has to be listed by hand), and for the game groups the plugin sources. It stores a hash of each of those files when the module passes. The next run only runs the modules where a hash differs, and `--list` names the file. Examples: changing `casualtieslink/pair.py` runs `unit.test_pair_fake` and nothing else; changing a plugin file reruns the game groups and not the offline ones; changing line endings alone reruns nothing. A module that failed runs again until it passes, and a module that was only skipped is not recorded as passed. State lives in `client/.test_state.json`.

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

### Plugin gate scenarios (stock Together with and without our plugins)

Our plugins (size, the character loader, the Avali pack) must behave as plain stock Together unless the host and the peer are both ours. `tests/test_gates.py` checks that with real games, one pair at a time, direct IP, no Steam, stock Together 5.4.0 on both. It runs only with `--pair`, in the group `gates`:

```bash
python run_tests.py --pair --only gates --match A_ --budget-seconds 400     # stock host, client with all plugins
python run_tests.py --pair --only gates --match C_ --budget-seconds 400     # host with plugins, client without
python run_tests.py --pair --only gates --match B_                          # both with plugins
python run_tests.py --pair --only gates --match D_                          # different pack sets
```

| Scenario | Host | Client | Checked |
|---|---|---|---|
| A | stock, none of our plugins | size, loader, Avali | the client's size gate is `NotOurs`; the loader and Avali are inert on both games (no channel, one log line saying characters are singleplayer only, no loader message of any kind sent, no skin applier, no custom character, `charType` 0 on every body); no error lines about our plugins in either log; the client sent only the size hello, two or three times and never after the timeout, and nothing else; the host sent nothing; `size @m 2` works locally; `size HostD 2` is refused with the host-needs-the-plugin text and no body changes |
| B | size | size | the size gates confirm (`Confirmed`, host roster has a confirmed peer); a host `size ClientD 2` shows on the client body on both games; after a disconnect and reconnect the client sees the current host size; the client sent only size messages |
| C | size, loader, Avali | none | the client has none of the types, its bodies are vanilla and carry no skin applier, the host sent it nothing (both games' counters stay empty), the host has no confirmed peer, `size ClientD 2` changes nothing on the client; no error lines |
| D | size, loader, sample pack | size, loader, Avali | both games keep running; the loader is inert on both so the pack sets cannot clash (same checks as A); no error lines |

The loader's current policy (its README) is that characters work in multiplayer only on the Together build that supports extra characters; on stock Together it sends nothing and changes nothing. So the character and pack-fingerprint checks of B and D run against the fork build, not stock, and are not part of these scenarios.

Scenario A also runs once per official stock build (`A_Stock550Tests`, `A_Stock540Tests`). Those install the flavour package (`CU_FLAVOUR_ZIP`, default `CasualtiesTogether-5.4.1+4.zip` in Downloads) into both game copies and start them with `--mp-flavour stock-5.5.0` or `stock-5.4.0`. They check that each log has one `CT_FlavourSwitch` line naming the flavour and that the Together line shows the matching version, on top of everything A checks. A fork host and a stock host need separate game folders, so mixed-flavour pairs use `host_together` and `client_together` in `ScenarioGames.start`.

Stock Together 5.4.0 logs seven `NullReferenceException` lines at startup by itself, on a host with none of our plugins too, so the error checks look only at lines that mention our plugins or the custom message layer.

How it observes: the gate states are read from the plugins' own static fields through `get` with `nonpublic` (`CasualtiesSize.TogetherBridge.Gate.Host`, `CasualtiesCharacters.StockBridge.channel.HostState`). The link plugin counts the custom messages a game sends: it patches the one place every message leaves through, `LiteNetLib.LiteNetPeer.SendInternal`, as soon as Together has loaded (before the first hello), and `net_counters` returns the counts by direction and message hash. Patching the Together wrappers instead missed messages, because the small ones are inlined by the compiler. `message_hash` asks Together itself for the hash of a name, so counts are matched to names (`CasualtiesSize.Hello`) without knowing the wire layout. The plugins' debug logging is switched on in the game copies by writing their `.cfg` files; the shipped defaults are not changed.

Setup is `casualtieslink/instances.py`. It makes two copies of the game folder once (`%TEMP%\CU-scenario-host` and `%TEMP%\CU-scenario-client`), and before every scenario rebuilds each copy's plugin set: it removes the plugin folders it manages, puts the stock Together folder in (without `Multiupdater.dll`), copies the freshly built link plugin, and installs the plugins that scenario names from the build outputs of the sibling folders (`size-mod/bin`, the newest release zip in `CU Characters/dist` and `CU Character Avali/dist`, the sample pack fixture). The operator's game folder is only read. The profile folder and PlayerPrefs are saved and restored around the whole run, and a persisted "Together disabled" preference is set back to enabled for the run. Paths come from the location of this repository (`CU_MODS_ROOT`, `CU_STOCK_TOGETHER_DIR` or `CU_STOCK_TOGETHER_DLL`, `CU_LINK_DLL` override them). Build the plugin first: `dotnet build plugin -c Release`.

### Desync scenarios (does the host keep what a client did)

The scenarios in `tests/desync_scenarios.py` follow the audit's list (`casualties-together-local/docs/desync_audit.md`). Each performs one action on the client through the link and reads the authoritative state on both games at 0 s, 2 s and 10 s (digging and the dynamite use their own offsets). The client's real hit path is used where the audit names it: the client holds a host-spawned pickaxe and `Body.UseItemInHand` runs with `targetLookPos` on the target, so Together's attack patch fires.

| Scenario | Client action | State read on both |
|---|---|---|
| `block_removal_by_client` | control: `WorldGeneration.DamageBlock` called directly | `GetBlock` at that position |
| `S1_block_dig_by_client` | pickaxe swings until the block breaks | `GetBlock` at 0, 3 and 8 s |
| `S2_block_crack_by_client` | one pickaxe swing | the block's entry in `blockDamages` |
| `S3_corpse_punch_by_client` | pickaxe swings at a corpse, client is Dune and host is not (own group `mixed-characters`) | corpse health (none if gone) |
| `S5_building_break_by_client` | pickaxe swings at the nearest breakable building | its health (none if gone) |
| `S6_door_open_by_client` | `Openable.OnUse` on the nearest instant-open door | its health (none if gone) |
| `S7_item_pickup_by_client`, `S7_item_drop_by_client`, `S7_item_throw_by_client` | `PickUpItem`, `DropItem`, `ThrowItem` | unparented items of that kind near the spot |
| `S9_eat_by_client` | `UseItemInHand` on bread after the host set the client's hunger to 40 | the client body's `hunger` |
| `S14_grenade_crater_by_client` | dynamite lit and thrown at a wall | sum of block ids in a 9 by 9 box, sampled at 6, 8 and 12 s |
| `container_load_by_client`, `container_unload_by_client` | `Container.LoadItem`, `UnloadItem` on a pouch | `Container.itemCount` |

Not written: S4 (a physics corpse, no verified way to make one dynamic), S8, S10, S11, S13 (no client driver found yet) and S12 (needs two clients; the rig has one).

The engine is `casualtieslink/desync.py`. Each scenario ends in one verdict: `persisted` (both agree and the change is there from 0 s), `reverted-by-host` (the client had the change and it was overwritten with the old value), `diverged` (the games disagree), `not-there-from-the-start` or `never-changed`. The test passes only on `persisted`. The report prints the baseline and the host and client value at each time, marks rows where the games disagree, names the build and the SHA-256 of its `CasualtiesMP.dll`, and is saved as JSON in `.state/desync_reports/<scenario>__<build>@<hash8>.json`.

Scenarios that share a Together build and startup flags run inside one launch of the host and the client, one after another. Each scenario picks its own target again and starts by emptying the client's hand and releasing input, so the verdicts are independent. A scenario that fails in its setup fails alone; the launch goes on. Only a different build, flavour or startup flag needs another launch. The startup groups are `default`, `mixed-characters` (a Dune client) and `hand-mining` (both games with `--mp-verbose`).

Builds, chosen with `--together` or listed with `--builds`:

| Build | What is installed |
|---|---|
| `stock-5.5.0`, `stock-5.4.0`, `fork` | the flavour package (`CU_FLAVOUR_ZIP`), started with `--mp-flavour` |
| `official-5.5.0` | `plugins/Together` of the official 5.5.0 release, extracted by `casualtieslink/officialstage.py` into `.state/stages/official-5.5.0` (`CU_OFFICIAL_STAGE`), without the updater |
| `fullbuild-control`, `fullbuild-fixed`, `spectator-fix`, `pr24-control`, `pr24-fixed`, `pr24-fixed-verbose`, `pr24-control-verbose` | `plugins/Together` of a build staged by the Together source session under `Private CU together/build/stage_*`, without the updater; each folder can be moved with its own variable (`CU_FULLBUILD_CONTROL_STAGE`, `CU_FULLBUILD_FIXED_STAGE`, `CU_SPECTATOR_FIX_STAGE`, `CU_PR24_CONTROL_STAGE`, `CU_PR24_FIXED_STAGE`, `CU_PR24_VERBOSE_STAGE`, `CU_PR24_CONTROL_VERBOSE_STAGE`). The DLL md5 of each is pinned in `unit/test_fullbuild_stages.py` |

The test class name carries the build and the first eight hex digits of the DLL hash (`Desync_stock_5_5_0_9bb980b8_default`), and a test checks that both games run the DLL with that hash. Every report names its launch, repetition, game version, network profile and proxy seed.

The client connects to the host through a UDP proxy (`casualtieslink/udpproxy.py`, client port 7791, host 7790). Its network profile changes while the games run, without dropping the connection: `delay_ms`, `jitter_ms`, `loss` and `reorder` (the share of packets that get 30 ms extra, so they can arrive late). Jitter, loss and reorder draw from a generator seeded per launch, and the seed is in the report. Packets keep their order in each direction while jitter and reorder are 0 and the delay does not change; jitter, reorder and lowering the delay mid stream can let a later packet overtake an earlier one. `proxy.set(delay_ms=100, jitter_ms=60)` is the Python interface. A loopback only HTTP control (`GET /get`, `POST /set` with a JSON object) is off unless the launcher starts it with `proxy.start_control(port)`; it refuses any peer that is not loopback and any other `Host` header.

A scenario that depends on the network (the series scenarios) runs once per profile of `--net DELAY:JITTER[:LOSS[:REORDER]]`; the other scenarios run once. The runner applies the profile before each scenario and restores a direct link after it. `--repeat N` runs every scenario N times inside the same launch.

```bash
python run_tests.py --pair --only desync --builds pr24-fixed stock-5.5.0 --net 100:0 100:60 250:100 --repeat 3 --match hold_mining
python run_tests.py --only desync --builds fork stock-5.5.0 --net 100:0 --list
python run_tests.py --pair --only desync --together stock-5.5.0 --budget-seconds 600
python run_tests.py --pair --only desync --together stock-5.5.0 --mutate skip-client-action
```

`--builds` plans one launch per build and startup group and prints the launches, their scenario runs and how many launches one launch per run would have needed; with `--pair` it runs them, each launch as its own process with a time budget of 60 s per scenario run plus the startup. Before any game starts, the runner asks every registered scenario module to check its planned gates and counts against `--repeat` (for the spawned crate scenario: re-seat target not stricter than the start gate, gate inside the bare-hand reach, early stops below the planned attempts); a contradiction prints `PREFLIGHT:` lines and exits 2 without launching. `--list` stops after the plan. `--together` runs a single launch. A series scenario also has its own 120 s budget for the hits. `--mutate skip-client-action` leaves out the client's action, so every scenario reports `never-changed` and fails.

The hand mining scenarios (`hand_mining_cracks`, one click every 0.75 s, and `hold_mining_cracks`, `Body.UseItemInHand` every 20 ms so the game's own attack cooldown gates each swing) record the crack counter and the tile id on both games every 0.25 s from the first swing until 10 s after the break. Verdicts: `persisted`, `crack-reset` (the counter dropped while the block was still there), `reappeared-after-break` (the block was back on a machine after it had been gone) and `never-broke`. The report also gives the block id and health, the swings the client sent, the swings the host took (read from the host's crack steps), the host log counts for `hit server cooldown`, `range`, `unresolved` and `drop`, the host copy of the client body against its real position at each swing, and hints that name the divergence pattern.

The held-click scenarios take a fresh block for every run: the host places block 8 (health 60) in the first free column 2, -2, 3 or -3 beside the client with `SetBlock`, both games must show it before the run starts, and the cell is cleared again afterwards, so a launch can mine as many blocks as it has runs. Four scenarios, each selected by one `--match` fragment:

| Fragment | Group | Client aim | Characters |
|---|---|---|---|
| `hold_mining_cracks` | `hand-mining` | fixed on the block | Experiment and Experiment |
| `aim_circle_mining_cracks` | `hand-mining` | circles the block at 0.4 block radius, one turn in 3 s; the crack counters of the block and its eight neighbours are read on both games, and increases on other tiles are counted | Experiment and Experiment |
| `dune_client_hold_mining` | `mixed-hand-mining` | fixed | Dune client, Experiment host |
| `dune_client_aim_circle` | `mixed-hand-mining` | circle | Dune client, Experiment host |

A network profile can carry its own repetition count, `DELAY:JITTER@COUNT`:

```bash
python run_tests.py --pair --only desync --builds pr24-fixed --net 0:0@15 100:0@15 --match hold_mining_cracks
python run_tests.py --pair --only desync --builds pr24-fixed --net 0:0@15 100:0@15 --match aim_circle_mining_cracks
python run_tests.py --pair --only desync --builds pr24-fixed --net 0:0@10 100:0@10 --match dune_client_hold_mining
python tools/desync_summary.py L1-pr24-fixed-hand-mining
```

`tools/desync_summary.py` sums the reports of one launch per network profile: blocks mined, blocks that reappeared, swings sent, received and accepted, losses by reason, and the delay the proxy planned.

The offline tests (`unit/test_desync.py`, `unit/test_desync_series.py`, `unit/test_desync_scenarios.py`, `unit/test_launchplan.py`, `unit/test_udpproxy.py`, `unit/test_run_arguments.py`) cover the verdicts, the report text, the file names, the build and hash handling, the launch plan, the run expansion, the proxy and its control, and the scenario helpers against the fake game server. The game-side reads are untested until the scenarios have run on a game.

### Friends zip lobby check (the shipped mod set on two game copies)

`tests/test_friends_zip.py` (group `friends-zip`) gives both game copies exactly the plugin set of a friends zip: `casualtieslink/friendszip.py` unpacks the zip over the copy (all files except `INSTALL.txt` and `changelog.txt`), replaces the copy's `Together` folder, compares every DLL's md5 with the zip, and removes any other plugin folder from the copy (never from the installed game) and reports it. The only addition is the CasualtiesLink plugin (the harness needs it to drive the games) and a loader debug config. The zip comes from `CU_FRIENDS_ZIP` (default `Downloads/CasualtiesUnknown-Mods.zip`); the build choice is `friends-zip`.

One launch runs, in order: the host alone in a world, a fresh client joining late with the custom pick (SelectCharacter(3) through the select, assertions on both machines), a banded PvP run of five punches from that client, the launch log counts, a reconnect without a re-pick and one with an explicit re-pick (the tag of the client's own body is read after each), and a fresh pair where the host picks the custom character and the client a plain one. Assertions read, per body, `NetBody.player.customCharacter` and `NetBody.syncBody.customCharacter.Value`, the `CharacterIdTag`, the loader's `CustomCharacter` component and the body species; the zip md5 and the Together DLL md5 are pinned in the live module, and the PvP punches are accepted anywhere from 2.0 to 3.6 when the client cannot be held in the 2.5 to 3.2 band, with the distance recorded per punch; the loader's page state is read from the private static `CasualtiesCharacters.CharacterMenu.view`. Results are written to `.state/friends_zip_reports/friends_zip.json`. Continue from a save and a fingerprint mismatch are not wired.

```bash
python run_tests.py --pair --only friends-zip
```

### Paged character select (singleplayer, friends zip plus a test pack)

`tools/paged_select.py --zip-md5 <md5> [--width W --height H --characters N]` starts one singleplayer game (`--mp-disable`) from a copy with the friends zip plugin set and a generated test pack (`casualtieslink/pagedselect.py`), snapshots the profile first, and keeps the game up with the link on port 7650 until a `stop` file appears in `.state/paged_select`. It then closes the game, deletes the copy and restores the profile. `--loader-dll PATH` puts a CasualtiesCharacters.dll over the zip's loader in the copy and records its md5. The screen is read through the link. `tools/paged_select_verify.py` drives the running session with real OS clicks and keys (`casualtieslink/oswindow.py`) at 16:9 and 16:10: arrow labels and paging, one click per slot, and the PageUp and PageDown keys, writing `.state/paged_select/verify.json`. The link's injected mouse does not reach the UI's EventSystem, so real input is needed for any UI button.

### Position control in the swing scenarios

The mining, crate and PvP scenarios hold the bodies instead of letting them stand free. Mining holds the client where it stands and parks and holds the host body 12 units to the left; the crate scenario does the same around its anchor and re-seats the client at the band middle by holding it there; the PvP scenario puts the victim back at its starting spot before every punch, holds it until just before the punch so the knockback is still measured, and keeps the client held at the band seat. Before the first swing a preflight checks both bodies against their targets and the minimum separation. A run that fails it is marked `INVALID` (crates and PvP: counted as a setup failure, never as a valid run or a missed swing; mining: its report carries `positionControl.ok = false` and `tools/mining_summary.py` counts it as `invalid` and leaves it out of every other count). Every mining report carries `startPositions` (host, client, separation, copy state) and `positionControl` (the preflight and the verification of each hold); crate and PvP reports carry the start positions in their target. `tools/recover_after_abort.py` stops stray games, restores the profile and deletes the scenario copies and a stale lock after an aborted run.

### Checking that the tests can fail

`tools/mutation_check.py` breaks the code on purpose in scratch copies, one change at a time (the list is `tools/mutants.json`), runs the offline tests against each copy and reports any change they did not notice. For example a second game being allowed, the save backup left behind, the plugin accepting an empty `Origin`, a held key one frame short.

```bash
python tools/mutation_check.py                  # all mutants, about 4 minutes
python tools/mutation_check.py --suite plugin   # only the plugin tests
python tools/mutation_check.py --match Origin
```

`--mutate` breaks the running game setup instead. `corrupt-save` truncates the save before loading, and the save and load test fails. `no-dune` leaves out `--mp-setchar 2`, and five Dune checks fail (`charType` 0 instead of 2, skills 9/8/7 instead of 17/18/0, no pain damping).

The stock client test needs `CU_STOCK_TOGETHER_DLL` to point at a stock 5.4.0 `CasualtiesMP.dll`, otherwise it is skipped.

Not covered: bandaging a limb from start to finish (only the start of the minigame is checked), a saved world beyond one field, fullscreen and focus behaviour, and Steam lobbies (the pair uses direct IP with `--mp-nosteam`).

## Contributing

Turn on the commit message check with `git config core.hooksPath .githooks`. A message is one line of at most 72 characters that says what changed, with no long dashes. A body is optional: at most five short lines after a blank line. The code has no comments. Names say what things are, and reasons go in this README or in a test.
