# CU TA Harness

Test automation (TA) for the Steam game Casualties: Unknown. A small BepInEx plugin, CasualtiesLink, runs inside the game and answers HTTP requests on the local machine. A Python client (standard library only) starts the game, sends it commands and runs the tests.

Repository: https://github.com/Sharkmare/CU-TA-Harness

The multiplayer tests use the Together mod: https://github.com/Sharkmare/casualties-together

```
plugin/   CasualtiesLink, C# (netstandard2.1, BepInEx 5, Harmony)
client/   the casualtieslink package, run_tests.py, tests/ (need the game), unit/ (no game)
tools/    check_commit_message.py, used by .githooks/commit-msg
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
| Input | `keybinds`, `input`, `mouse`, `input_probe`, `release_input` |
| Time and view | `timescale`, `step`, `screenshot`, `log` |
| Reflection | `find`, `get`, `set` |

`get` and `set` take a target (`player`, `camera`, `world`, `console`, `static:Type`, `type:Type[#n]`, `name:GameObject`, or `id:N` from a handle in an earlier reply) and a dotted path with `[index]` steps, for example `limbs[3].bleedAmount`, or `main.currentMinigame` on `static:MinigameBase`. Values are converted to the field's type: enums by name, vectors as `{x,y}`, object references as `id:N`. Pass `nonpublic:true` to reach non public members.

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

`.game.lock` marks that someone is using the game. `GameLock` creates it exclusively and only removes a lock it made itself. Do not start the game while the file exists.

## Two games at once (host and client)

`GamePair` starts the host from the installed folder (link port 7650) and the client from a copy of that folder (link port 7651). `testcopy.make_copy` makes the copy in `%TEMP%\CU-test-client`, or in the folder named by `CU_TEST_COPY_DIR`, refuses to put it inside this repository, and `GamePair` deletes it afterwards. Both games get `--mp-nosteam` and connect by IP address. The installed folder is never changed.

The two games share one profile: the `LocalLow\Orsoniks\CasualtiesUnknown` folder and the PlayerPrefs registry key. Unity has no per game profile, so `ProfileGuard` copies the folder and the registry key aside before the run and restores them afterwards. The tests do not save during a pair run. Each game writes its own `BepInEx/TogetherLogs/together.log`.

## Tests

```bash
cd client
python run_tests.py                       # groups whose files changed since they last passed
python run_tests.py --all
python run_tests.py --only world
python run_tests.py --list
python run_tests.py --attach              # use a game that is already running with the link
python run_tests.py --pair                # also run the host and client tests
python run_tests.py --pair --only pair --budget-seconds 900
python run_tests.py --pair --only pair --match visuals
python run_tests.py --mutate corrupt-save --only world
python run_tests.py --mutate no-dune --pair --only pair
```

`run_tests.py` takes the game lock, starts the game once, runs the chosen groups from `test_groups.json`, closes the game and records a hash of each passing group's files in `client/.test_state.json`. A group that failed runs again next time. A change to a file under `shared` runs every group. A group that was only skipped is not recorded as passed. `--match` runs only tests whose id contains the text, and `--budget-seconds` makes the run fail if it takes longer. The summary line shows the total time.

Groups marked `owns_game` (`inert`, `pair`) start their own games and run before the shared session.

| Group | What it checks |
|---|---|
| link | status, self description, unknown command, missing argument, missing header, `Origin` and `Host` refusals, `describe_type` |
| run | each character spawns the right player object, starting outside the menu fails, quitting to the menu sends `scene_changed` |
| world | spawn and pickup, the bandage minigame starts, damage with events and bleeding, console round trip and `heal`, writing then reading a field, stepping frames, injected keys move the player, a screenshot is a PNG, the pickup event, save and load |
| inert | without the switch the port is closed, nothing listens, the DISABLED line is logged and no config file appears; with `--link-port` it answers and logs ENABLED |
| pair | a Dune host and client: both see both players, the handshake is accepted, every body is `charType` 2 with skills 17/18/0 and gain multipliers 1/1/0.5 on both games, injuries are not damped by default, and with the DuneHardy rule switched on (`--mp-setrule DuneHardy 1`) pain gain is 0.7 and bleeding gain 0.8, a stock 5.4.0 client is refused with "Version mismatch"; mixed characters in both directions; remote bodies look like the local body of that character; a pointing arm has the same angle on the other game |
| client-offline | parsing, `--mp` flags, selection, the game lock, the test copy |
| repo-tools | the commit message check |

`--mutate` breaks something on purpose to show a test can fail. `corrupt-save` truncates the save before loading, and the save and load test fails. `no-dune` leaves out `--mp-setchar 2`, and five Dune checks fail (`charType` 0 instead of 2, skills 9/8/7 instead of 17/18/0, no pain damping).

The stock client test needs `CU_STOCK_TOGETHER_DLL` to point at a stock 5.4.0 `CasualtiesMP.dll`, otherwise it is skipped.

Not covered: bandaging a limb from start to finish (only the start of the minigame is checked), a saved world beyond one field, fullscreen and focus behaviour, and Steam lobbies (the pair uses direct IP with `--mp-nosteam`).

## Contributing

Turn on the commit message check with `git config core.hooksPath .githooks`. A message is one line of at most 72 characters that says what changed, with no long dashes. A body is optional: at most five short lines after a blank line. The code has no comments. Names say what things are, and reasons go in this README or in a test.
