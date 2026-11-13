# Client library and game control

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

The library modules and what each does are listed in `docs/ARCHITECTURE.md`. The `--mp-*` flag names come from the Together repo linked at the top.

`GameProcess.start()` refuses to start while a `CasualtiesUnknown.exe` is running, because starting a second copy of an online game loses the match. It copies `save.sv` aside before the tests and puts it back afterwards, or deletes the test save if there was none.

`CU-TA-Harness.game.lock` in the system temporary directory marks that someone is using the game. It is one file for the whole machine, so a second checkout or worktree is refused too; the game link ports are machine-wide. Set `CU_GAME_LOCK` to use another path. `GameLock` creates the file exclusively and only removes a lock it made itself. Do not start the game while the file exists.

## Two games at once (host and client)

`GamePair` starts the host from the installed folder (link port 7650) and the client from a copy of that folder (link port 7651). `testcopy.make_copy` makes the copy in `%TEMP%\CU-test-client`, or in the folder named by `CU_TEST_COPY_DIR`, refuses to put it inside this repository, and `GamePair` deletes it afterwards. Both games get `--mp-nosteam` and connect by IP address. The installed folder is never changed.

The two games share one profile: the `LocalLow\Orsoniks\CasualtiesUnknown` folder and the PlayerPrefs registry key. Unity has no per game profile, so `ProfileGuard` copies the folder and the registry key aside before the run and restores them afterwards. The tests do not save during a pair run. Each game writes its own `BepInEx/TogetherLogs/together.log`.
