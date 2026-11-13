# Scenarios that need two games

## Plugin gate scenarios (stock Together with and without our plugins)

Our plugins (size, the character loader, the Avali pack) must behave as plain stock Together unless the host and the peer are both ours. `live/test_gates.py` checks that with real games, one pair at a time, direct IP, no Steam, stock Together 5.4.0 on both. It runs only with `--pair`, in the group `gates`:

```bash
python client/run_tests.py --pair --only gates --match A_ --budget-seconds 400     # stock host, client with all plugins
python client/run_tests.py --pair --only gates --match C_ --budget-seconds 400     # host with plugins, client without
python client/run_tests.py --pair --only gates --match B_                          # both with plugins
python client/run_tests.py --pair --only gates --match D_                          # different pack sets
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

Setup is `casualtieslink/games/instances.py`. It makes two copies of the game folder once (`%TEMP%\CU-scenario-host` and `%TEMP%\CU-scenario-client`), and before every scenario rebuilds each copy's plugin set: it removes the plugin folders it manages, puts the stock Together folder in (without `Multiupdater.dll`), copies the freshly built link plugin, and installs the plugins that scenario names from the build outputs of the sibling folders (`size-mod/bin`, the newest release zip in `CU Characters/dist` and `CU Character Avali/dist`, the sample pack fixture). The operator's game folder is only read. The profile folder and PlayerPrefs are saved and restored around the whole run, and a persisted "Together disabled" preference is set back to enabled for the run. Paths come from the location of this repository (`CU_MODS_ROOT`, `CU_STOCK_TOGETHER_DIR` or `CU_STOCK_TOGETHER_DLL`, `CU_LINK_DLL` override them). Build the plugin first: `dotnet build plugin -c Release`.

## Scenario modules

Every module in `client/scenarios/` defines one or more scenarios of the desync engine and registers them with the runner. A scenario is selected with `--match <name fragment>`; its group decides which launch it shares with others.

| Module | Group | What it covers |
|---|---|---|
| `desync_scenarios` | `default`, `mixed-characters`, `hand-mining`, `mixed-hand-mining` | the audit list below and the hand mining series; also holds the shared helpers and the scenario registry |
| `hook_scenarios` | `hook-check` | held click mining, building hits, PvP melee and scatter distance on a build with the attack hook repaired |
| `regression_scenarios` | `hook-regression` | first swing and PvP punch must damage on both games once per swing |
| `evidence_scenarios` | `hook-evidence` | building hit with the log lines of each swing |
| `hook_evidence_mining` | `hook-evidence` | the mining scenario of `hook_scenarios` copied into the evidence group (scenario name `v2check_dig_cracks`) |
| `world_building` | `hook-evidence` | a building taken from the host's list and hit bare handed; also imports the other modules so they register |
| `spawned_crates` | `hook-evidence` | a fresh crate beside the client hit bare handed, with the client held in a distance band |
| `static_copy` | `hook-evidence` | a crate far from the client is Static on the client copy, then the client is moved next to it and swings at once |
| `pvp_banded` | `hook-evidence` | PvP punches from a held distance band, knockback and limb drift |
| `corpse_banded` | `hook-dune` | a Dune client hits a host-spawned corpse; `cantHit` on the host copy and the client copy |
| `wood_mining` | `wood-mining-dune`, `wood-mining-experiment` | a Dune or Experiment client mines a host-placed wood block at the cooldown's rate, Milky host: does the broken block come back on the client (block persistence, not swing landing); registered from the end of `desync_scenarios.py` |
| `corpse_chain` | `corpse-repro` | host Milky and client Dune, 25 swings at a corpse, health and `cantHit` against the session's prediction |
| `spectator_cam` | `spectator` | a dead client spectates the host: the camera must follow the host's body |
| `console_leak` | `console-leak` | whether the host's save line reaches a normal client or an admin client, reported as counts |
| `friends_zip` | none | helpers for `live/test_friends_zip.py` |

## Desync scenarios (does the host keep what a client did)

The scenarios in `scenarios/desync_scenarios.py` follow the audit's list (`casualties-together-local/docs/desync_audit.md`). Each performs one action on the client through the link and reads the authoritative state on both games at 0 s, 2 s and 10 s (digging and the dynamite use their own offsets). The client's real hit path is used where the audit names it: the client holds a host-spawned pickaxe and `Body.UseItemInHand` runs with `targetLookPos` on the target, so Together's attack patch fires.

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

The engine is `casualtieslink/scenarioengine/desync.py`. Each scenario ends in one verdict: `persisted` (both agree and the change is there from 0 s), `reverted-by-host` (the client had the change and it was overwritten with the old value), `diverged` (the games disagree), `not-there-from-the-start` or `never-changed`. The test passes only on `persisted`. The report prints the baseline and the host and client value at each time, marks rows where the games disagree, names the build and the SHA-256 of its `CasualtiesMP.dll`, and is saved as JSON in `.state/desync_reports/<scenario>__<build>@<hash8>.json`.

Scenarios that share a Together build and startup flags run inside one launch of the host and the client, one after another. Each scenario picks its own target again and starts by emptying the client's hand and releasing input, so the verdicts are independent. A scenario that fails in its setup fails alone; the launch goes on. Only a different build, flavour or startup flag needs another launch. The startup groups are `default`, `mixed-characters` (a Dune client) and `hand-mining` (both games with `--mp-verbose`).

Builds, chosen with `--together` or listed with `--builds`:

| Build | What is installed |
|---|---|
| `stock-5.5.0`, `stock-5.4.0`, `fork` | the flavour package (`CU_FLAVOUR_ZIP`), started with `--mp-flavour` |
| `pr24-3d060fe-plain`, `pr24-3d060fe-corpse-fix`, `pr24-3d060fe-corpse-fix2` | `plugins/Together` and `plugins/CUCoreLib` of a build staged by the Together source session under `Private CU together/build/stage_*`, without the updater; each folder can be moved with its own variable (`CU_PR24_3D060FE_PLAIN_STAGE`, `CU_PR24_3D060FE_CORPSE_FIX_STAGE`, `CU_PR24_3D060FE_CORPSE_FIX2_STAGE`). The DLL md5 of each is pinned in `unit/test_fullbuild_stages.py`, together with the md5 of CUCoreLib, and the preflight refuses a build when the library is missing |
| `swingburst-package` | the Together and CUCoreLib plugin folders of the friend package, taken from the extracted zip: `CU_SWINGBURST_PACKAGE_STAGE` names its `BepInEx` folder (there is no default), the DLL md5 is `f1f2214830d7aadaa8ff565f844ca882` |

The test class name carries the build and the first eight hex digits of the DLL hash (`Desync_stock_5_5_0_9bb980b8_default`), and a test checks that both games run the DLL with that hash. Every report names its launch, repetition, game version, network profile and proxy seed.

The client connects to the host through a UDP proxy (`casualtieslink/games/udpproxy.py`, client port 7791, host 7790). Its network profile changes while the games run, without dropping the connection: `delay_ms`, `jitter_ms`, `loss` and `reorder` (the share of packets that get 30 ms extra, so they can arrive late). Jitter, loss and reorder draw from a generator seeded per launch, and the seed is in the report. Packets keep their order in each direction while jitter and reorder are 0 and the delay does not change; jitter, reorder and lowering the delay mid stream can let a later packet overtake an earlier one. `proxy.set(delay_ms=100, jitter_ms=60)` is the Python interface. A loopback only HTTP control (`GET /get`, `POST /set` with a JSON object) is off unless the launcher starts it with `proxy.start_control(port)`; it refuses any peer that is not loopback and any other `Host` header.

Stall and flush approximates a link that goes quiet and then delivers everything at once (the way a relayed Steam connection behaves). For the client to host direction (and the host to client direction when `stall_to_client` is 1) the proxy holds every packet for a random stretch and then releases all held packets back to back, in arrival order, `stall_gap_ms` apart (default 0); after that the normal delay and jitter resume. A stall starts a random time after the previous one ended, uniform in `stall_interval_ms` +- `stall_interval_spread_ms`, and lasts uniform in `stall_duration_ms` +- `stall_duration_spread_ms` (each spread at most its mean; a mean of 0 for the interval or the duration switches stalls off). The stall draws use their own generator seeded from the proxy seed, so switching a stall on does not change the jitter sequence, and the stall never drops or reorders a packet: held packets leave in arrival order, a flush waits for any earlier packet still in flight, and a later packet is never due before the last flushed one. Every finished stall is in `proxy.stall_trace` (direction, start, end, packets held, first and last release time, gap) and in the report as `stallTrace`; `proxy.trace_since(mark)` lists every packet as (received at, direction, size, delay ms, due at), with the due time of a held packet being its release. Profiles carry the stall after the four network values: `--net DELAY:JITTER:LOSS:REORDER:STALL_INTERVAL:INTERVAL_SPREAD:STALL_DURATION:DURATION_SPREAD:GAP:TO_CLIENT`, for example `--net 100:75:0:0:800:300:400:100` is 100 ms delay, up to 75 ms jitter and a stall every 0.5 to 1.1 s that holds packets for 0.3 to 0.5 s. `tools/proxy_mutation_check.py` proves the stall tests fail when the mode is broken.

A scenario that depends on the network (the series scenarios) runs once per profile of `--net DELAY:JITTER[:LOSS[:REORDER]]`; the other scenarios run once. The runner applies the profile before each scenario and restores a direct link after it. `--repeat N` runs every scenario N times inside the same launch.

```bash
python client/run_tests.py --pair --only desync --builds pr24-3d060fe-plain stock-5.5.0 --net 100:0 100:60 250:100 --repeat 3 --match hold_mining
python client/run_tests.py --only desync --builds fork stock-5.5.0 --net 100:0 --list
python client/run_tests.py --pair --only desync --together stock-5.5.0 --budget-seconds 600
python client/run_tests.py --pair --only desync --together stock-5.5.0 --mutate skip-client-action
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
python client/run_tests.py --pair --only desync --builds pr24-3d060fe-plain --net 0:0@15 100:0@15 --match hold_mining_cracks
python client/run_tests.py --pair --only desync --builds pr24-3d060fe-plain --net 0:0@15 100:0@15 --match aim_circle_mining_cracks
python client/run_tests.py --pair --only desync --builds pr24-3d060fe-plain --net 0:0@10 100:0@10 --match dune_client_hold_mining
python tools/desync_summary.py L1-pr24-3d060fe-plain-hand-mining
```

`tools/desync_summary.py` sums the reports of one launch per network profile: blocks mined, blocks that reappeared, swings sent, received and accepted, losses by reason, and the delay the proxy planned.

The offline tests (`unit/test_desync.py`, `unit/test_desync_series.py`, `unit/test_desync_scenarios.py`, `unit/test_launchplan.py`, `unit/test_udpproxy.py`, `unit/test_run_arguments.py`) cover the verdicts, the report text, the file names, the build and hash handling, the launch plan, the run expansion, the proxy and its control, and the scenario helpers against the fake game server. The game-side reads are untested until the scenarios have run on a game.

## Friends zip lobby check (the shipped mod set on two game copies)

`live/test_friends_zip.py` (group `friends-zip`) gives both game copies exactly the plugin set of a friends zip: `casualtieslink/games/friendszip.py` unpacks the zip over the copy (all files except `INSTALL.txt` and `changelog.txt`), replaces the copy's `Together` folder, compares every DLL's md5 with the zip, and removes any other plugin folder from the copy (never from the installed game) and reports it. The only addition is the CasualtiesLink plugin (the harness needs it to drive the games) and a loader debug config. The zip comes from `CU_FRIENDS_ZIP` (default `Downloads/CasualtiesUnknown-Mods.zip`); the build choice is `friends-zip`.

One launch runs, in order: the host alone in a world, a fresh client joining late with the custom pick (SelectCharacter(3) through the select, assertions on both machines), a banded PvP run of five punches from that client, the launch log counts, a reconnect without a re-pick and one with an explicit re-pick (the tag of the client's own body is read after each), and a fresh pair where the host picks the custom character and the client a plain one. Assertions read, per body, `NetBody.player.customCharacter` and `NetBody.syncBody.customCharacter.Value`, the `CharacterIdTag`, the loader's `CustomCharacter` component and the body species; the zip md5 and the Together DLL md5 are pinned in the live module, and the PvP punches are accepted anywhere from 2.0 to 3.6 when the client cannot be held in the 2.5 to 3.2 band, with the distance recorded per punch; the loader's page state is read from the private static `CasualtiesCharacters.CharacterMenu.view`. Results are written to `.state/friends_zip_reports/friends_zip.json`. Continue from a save and a fingerprint mismatch are not wired.

```bash
python client/run_tests.py --pair --only friends-zip
```

## Paged character select (singleplayer, friends zip plus a test pack)

`tools/paged_select.py --zip-md5 <md5> [--width W --height H --characters N]` starts one singleplayer game (`--mp-disable`) from a copy with the friends zip plugin set and a generated test pack (`casualtieslink/charselect/pagedselect.py`), snapshots the profile first, and keeps the game up with the link on port 7650 until a `stop` file appears in `.state/paged_select`. It then closes the game, deletes the copy and restores the profile. `--loader-dll PATH` puts a CasualtiesCharacters.dll over the zip's loader in the copy and records its md5. The screen is read through the link. `tools/paged_select_verify.py` drives the running session with real OS clicks and keys (`casualtieslink/charselect/oswindow.py`) at 16:9 and 16:10: arrow labels and paging, one click per slot, and the PageUp and PageDown keys, writing `.state/paged_select/verify.json`. The link's injected mouse does not reach the UI's EventSystem, so real input is needed for any UI button.

## Position control in the swing scenarios

The mining, crate and PvP scenarios hold the bodies instead of letting them stand free. Mining holds the client where it stands and parks and holds the host body 12 units to the left; the crate scenario does the same around its anchor and re-seats the client at the band middle by holding it there; the PvP scenario puts the victim back at its starting spot before every punch, holds it until just before the punch so the knockback is still measured, and keeps the client held at the band seat. Before the first swing a preflight checks both bodies against their targets and the minimum separation. A run that fails it is marked `INVALID` (crates and PvP: counted as a setup failure, never as a valid run or a missed swing; mining: its report carries `positionControl.ok = false` and `tools/mining_summary.py` counts it as `invalid` and leaves it out of every other count). Every mining report carries `startPositions` (host, client, separation, copy state) and `positionControl` (the preflight and the verification of each hold); crate and PvP reports carry the start positions in their target. `tools/recover_after_abort.py` stops stray games, restores the profile and deletes the scenario copies and a stale lock after an aborted run.

## All or nothing swings

A swing scenario run is all or nothing. A missed swing fully invalidates a test, so setup must make a setup-caused miss impossible (`casualtieslink/scenarioengine/swinggate.py`). Every swing is gated immediately before it fires, from fresh reads: the body within 0.05 of its seat by the holder's view and `rb.position`; limb 1 within 0.5 of its rest pose relative to the body (limb 0 is recorded, not gated: it is not the swing origin and it moves with the swing animation) and limb 1 within 4.5 of the target (the game's attack distance; limbs of landed swings were up to 4.03 from it); `isRight` matching the side of the target; the attack cooldown ready; the target present with health, its copy state (bodyType, physicsActive) recorded on both machines; the distance inside the band; and no other body within 6 units of the body or the target. The gate is read until it passes (`wait_ready`, 0.1 s polls, 3 s timeout) because the limb and the body are in recoil for a moment after a swing; the passing read is fresh and the swing is fired at once. A swing whose gate has not passed within the timeout is not fired and the run is INVALID, with the gate named. After any move or teleport the swings wait until both limbs keep the same place relative to the body on two consecutive reads and limb 1 is within reach of the target (`settle_limbs`, 6 s timeout, then INVALID); that read is the rest pose. A swing fired with every gate passed that still did not land makes the run a FAIL, a finding about the product, reported apart from INVALID; the gate values at fire time stay in every swing record (`gate`). A run is valid only when every swing landed, so reports show runs (valid n of m) and the invalid and fail lists, never partial swing counts. The crate, static copy and PvP scenarios gate every swing; the corpse scenario gates the first swing and judges the chain by its sampler (facing, parked distance), because its swings are not counted as landed and a gate read per swing would slow the chain below a player's rate; the mining scenarios hold the click and count blocks, not swings. `python tools/gate_mutation_check.py` mutates each gate and the verdict and fails when a mutation is not caught by `unit/test_swinggate.py`.

## Other programs for the scenario runs

- `python tools/wood_mining_table.py D=.state/wood_fd_reports:d100-j100 E=.state/wood_fe_reports:d100-j100 [--format text|markdown] [--runs]` prints one result table for the wood mining launches (`LABEL=REPORT_DIRECTORY:NETWORK`, the network being the `d<delay>-j<jitter>` part of the report file names); `--runs` prints the per-run bunching evidence instead of the summary.
- `python tools/pr24_summary.py REPORTS_DIRECTORY CLIENT_LOG [--utc-offset-hours H]` counts the `[PR24V]` lines of a client log per mining run, using each report's wall clock window.
- `python tools/package_log_check.py LOG_DIRECTORY [--expect-burst]` checks the BepInEx logs of one launch of a friend package (`host-LogOutput.log` and `client-LogOutput.log`): Together and CUCoreLib loaded once, the Body.Attack transpiler succeeded once, no `RESYNCGUARD` and no `STEAMLIKE` text, and the `SWINGBURST` lines of the host. Exit code 1 when a check fails.
- `python tools/steam_selfjoin.py --label NAME [--stage-choice pr24-3d060fe-plain-stage] [--dry-run]` runs the Steam self-join experiment on two harness copies with one account. It only uses harness copies, makes the lobby private with a throwaway password, refuses a stage DLL whose `CreateLobby` forces a public lobby, never touches Steam credentials or settings, and sends no invites. `--dry-run` runs the safety checks without a game.
