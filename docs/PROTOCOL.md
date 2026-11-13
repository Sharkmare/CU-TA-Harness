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

`hold_body` takes `id` or `local`, `x`, `y` and a `tolerance` (0.001 to 5, default 0.05). A held body is put back at the target on every physics tick and before every frame is drawn, and every velocity under the body is zeroed, so it cannot drift, be pushed or fall off a ledge. `hold_status` reports, per hold, the target, the current position, the drift now, the largest drift seen before a correction, how many ticks exceeded the tolerance and whether the body is still found; `heldWithinTolerance` is true only after at least one tick with none over the tolerance. A hold on a body only acts on the game that holds it, so hold each player on its own machine. `casualtieslink/scenarioengine/positioncontrol.py` wraps it; `docs/SCENARIOS.md` describes `place_and_hold`, `seat_pair`, `preflight_pair` and the roles of the two bodies.

Events: `link_started`, `scene_changed`, `player_ready`, `console`, `item_picked_up`, `damage` (a limb lost health, found by checking every frame), `death`, `exception` (a Unity error or exception).

Key and mouse input works by patching `Input.GetKey`, `GetKeyDown`, `GetKeyUp`, `GetMouseButton(Down)` and `mousePosition`. A key sent on frame F is held on frames F+1 to F+n, so the game never misses the first frame. The real keyboard still works.

## What the game does that the tests have to work around

- With the Together mod active the game refuses singleplayer, so `start_run` stays at the menu. `run_tests.py` starts the game with `--mp-disable`.
- Any cheat command opens the console window, and an open console blocks player input. `console` closes it again unless you pass `keep_open`. The Together mod can also leave the console open on the host at start, so the pair tests call `close_console` first.
- The game sets `Time.timeScale` itself in several places, so pausing with `timescale 0` does not last. `step` puts back whatever it found.
- `start_run` sets the `didbasiccourse` PlayerPref, otherwise a tutorial warning stops the run from starting. The reply tells you the old value.
- The player object is named `Experiment(Clone)`, `Milky(Clone)` or `Dune(Clone)`.
- A second `CasualtiesUnknown.exe` started from the installed folder quits after about a second. One started from a copy of the folder runs.
