# CU TA Harness

Test automation (TA) for the Steam game Casualties: Unknown. A small BepInEx plugin, CasualtiesLink, runs inside the game and answers HTTP requests on the local machine. A Python client (standard library only) starts the game, sends it commands and runs the tests.

Repository: https://github.com/Sharkmare/CU-TA-Harness

The multiplayer tests use the Together mod: https://github.com/Sharkmare/casualties-together

## Layout

```
plugin/         CasualtiesLink, C# (netstandard2.1, BepInEx 5, Harmony)
plugin-tests/   offline tests of the plugin's Unity-free code (console program, .NET 9)
client/         Python: the casualtieslink library, scenarios/, live/ and unit/ tests, profiles/, run_tests.py
tools/          operator programs (summaries, result tables, recovery, mutation checks) and the commit message check
docs/           architecture and topic documents
```

`docs/ARCHITECTURE.md` explains what lives where and where a new scenario, link command or test goes.

## Build and install

```bash
dotnet build plugin -c Release
cp plugin/bin/CasualtiesLink.dll "C:/Program Files (x86)/Steam/steamapps/common/Casualties Unknown/BepInEx/plugins/CasualtiesLink/"
```

Close the game before copying. The project reads the game's `Managed` folder and `BepInEx/core`; point it at another install with `-p:GameDir=...`. A good start writes `CasualtiesLink ENABLED on port N` to `BepInEx/LogOutput.log`.

Paths outside this repository come from the location of the repository or from environment variables (`CU_MODS_ROOT`, `CU_STOCK_TOGETHER_DIR`, `CU_LINK_DLL` and others); each is named where it is used in `docs/`.

## Run the tests

One entry point runs everything, `client/run_tests.py`. It only reruns what changed since the last pass.

```bash
python client/run_tests.py --offline        # offline Python tests and the plugin tests; never starts a game
python client/run_tests.py --offline --all  # the same, forced to run everything
python client/run_tests.py --pair --only desync --together stock-5.5.0   # live scenarios on two games
```

Live groups need a free machine with the game installed; `docs/TESTING.md` lists every group, flag and what a run does to the game folder and profile. The scenarios that start two games are in `docs/SCENARIOS.md`.

A few offline tests read folders next to this repository (the `mods` folder that holds it). When the repository sits elsewhere, for example in a git worktree, set `CU_MODS_ROOT` to that `mods` folder.

## Documents

| Document | Content |
|---|---|
| `docs/ARCHITECTURE.md` | layout, module map, rules, where new things go |
| `docs/PROTOCOL.md` | the plugin's off switch, security, commands, events, game quirks |
| `docs/CLIENT.md` | the command line client, game lock, host and client pair |
| `docs/TESTING.md` | the runner, test groups, change selection, result tables for a PR, mutation check |
| `docs/SCENARIOS.md` | gate, desync, friends zip, paged select and swing scenarios, and the programs around them |

## Contributing

Turn on the commit message check with `git config core.hooksPath .githooks`. A message is one line of at most 72 characters that says what changed, with no long dashes. A body is optional: at most five short lines after a blank line. Names say what things are, and reasons go in the docs or in a test.
