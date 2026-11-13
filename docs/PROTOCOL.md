# Link plugin: switch, security, protocol

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

`hold_body` takes `id` or `local`, `x`, `y` and a `tolerance` (0.001 to 5, default 0.05). A held body is put back at the target on every physics tick and before every frame is drawn, and every velocity under the body is zeroed, so it cannot drift, be pushed or fall off a ledge. `hold_status` reports, per hold, the target, the current position, the drift now, the largest drift seen before a correction, how many ticks exceeded the tolerance and whether the body is still found; `heldWithinTolerance` is true only after at least one tick with none over the tolerance. A hold on a body only acts on the game that holds it, so hold each player on its own machine. `casualtieslink/scenarioengine/positioncontrol.py` wraps it: `place_and_hold` seats a body and proves it stays, `seat_pair` holds the attacking client at its seat and parks the other player 12 units away (the client, which takes part in the swing, is always held to 0.05. The parked host is held to the same 0.05 by default; with `parked_policy="recorded"` it is held at `PARKED_TOLERANCE` (0.5, a recorded number, not an abort) and its drift never fails the seat, because its position reads were seen climbing by tenths while the holder reported no exceeded tick. The caller then has to check how close the parked host stays: the report keeps `parkedHost` with the raw drift reads, a `parked_snapshot` (link read, the holder's own view, and the extra transform, limb and velocity paths the game answers) at every verification poll, and the corpse repro takes one more at every swing and labels the result confounded when the nearest read is closer than 6 units to the client or the corpse. A seat that fails its verification is released and tried again, up to 3 attempts; `seatAttempts` and `earlierAttemptIssues` are in the report), `preflight_pair` checks both bodies are at their targets within the tolerance and at least 2.0 apart, and `start_positions` records both bodies at the start of a run. Bodies have roles. A body that takes part in the swing (the attacking client, and the victim of a punch) is held to 0.05 and its seat is accepted only when the holder's own view (`hold_status`) and `rb.position` both sit within 0.05 of the target and of each other (`judge_seat`, `verify_swinging_body`, `preflight_views`); the link position read is recorded next to them and a disagreement is reported as `linkReadDisagrees`, it does not fail the seat. A body that is only parked (the host in the crate runs) is held at `PARKED_TOLERANCE` and judged by distance only: at least 6 units from the client and the target by the nearest of its readable position reads (`parked_distance_problems`), at the preflight and at every swing; a closer reading marks the run confounded, drift is recorded, never a failure. The static-copy scenario spawns the far crate again at farther columns (up to 4 attempts) while the client copy is not Static, records the copy state at each distance (`farAttempts`), and counts no result when no distance gave a Static copy. With no far pocket at all it lists the buildings nearest the client with the host and client copy states (`STATIC OFFER` in the output) and adopts the first one whose client copy is Static and that can be hit as the swing target (`adopted`: the cleanup never destroys it). After the one-step move the swings wait until the client's limb 1 is within 4 units of the crate on two readings in a row (`limbSettle` in the report): after that move the arm limb can lag the body by about 9 units, and every swing that missed in the static runs had it there. With `DIAGNOSTIC_RUN` set to 1 the crate scenario's first run in a launch is a diagnostic run (the old setup: crate beside the anchor, client re-seated by the band) that records, from the seat to the first swing, a trace every 0.07 s in `target.diagnostic`: the client's holder view, link read, `rb.position`, limbs and `rb.velocity`, the crate's position and velocity on the host, the host body, and the client to crate distance (colliders cannot be read over the link). Every other run (all runs while `DIAGNOSTIC_RUN` is 0, the default) uses the settled setup: the crate is spawned at the band distance from the client's anchor, waits until its position step has stayed near zero for 0.5 s (`rb.velocity` is not used: a body resting on the floor reads a velocity flipping between 0 and about 1 each tick), and only then is the client seated at the anchor and verified by the holder's view and `rb.position`; a second offset inside the band is tried when the seat does not verify (`settledAttempts` in the report). The band re-seat holds the client at its standing height (the anchor height), not the crate's height: a crate rests lower than a standing body, and a seat at the crate height pulls the held body into the floor, where it fights the hold and drifts by up to 0.6.

Events: `link_started`, `scene_changed`, `player_ready`, `console`, `item_picked_up`, `damage` (a limb lost health, found by checking every frame), `death`, `exception` (a Unity error or exception).

Key and mouse input works by patching `Input.GetKey`, `GetKeyDown`, `GetKeyUp`, `GetMouseButton(Down)` and `mousePosition`. A key sent on frame F is held on frames F+1 to F+n, so the game never misses the first frame. The real keyboard still works.

## What the game does that the tests have to work around

- With the Together mod active the game refuses singleplayer, so `start_run` stays at the menu. `run_tests.py` starts the game with `--mp-disable`.
- Any cheat command opens the console window, and an open console blocks player input. `console` closes it again unless you pass `keep_open`. The Together mod can also leave the console open on the host at start, so the pair tests call `close_console` first.
- The game sets `Time.timeScale` itself in several places, so pausing with `timescale 0` does not last. `step` puts back whatever it found.
- `start_run` sets the `didbasiccourse` PlayerPref, otherwise a tutorial warning stops the run from starting. The reply tells you the old value.
- The player object is named `Experiment(Clone)`, `Milky(Clone)` or `Dune(Clone)`.
- A second `CasualtiesUnknown.exe` started from the installed folder quits after about a second. One started from a copy of the folder runs.
