using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CasualtiesLink
{
    public static partial class Commands
    {
        private const string TutorialDonePreference = "didbasiccourse";
        private static readonly string[] CharacterPrefabNames = { "Experiment", "Milky", "Dune" };

        private static void RegisterRun()
        {
            Add("start_run", "From the main menu, selects a character and run settings and starts a new run. Completes when the player exists in the world.", args =>
            {
                if (PreRunScript.instance == null) throw new Exception("not at the main menu (state is " + GameState.Name() + ")");
                int character = Int(args, "character", 0);
                if (character < 0 || character > 2) throw new Exception("character must be 0 (Experiment), 1 (Milky) or 2 (Dune)");
                PreRunScript menu = PreRunScript.instance;
                int tutorialFlagBefore = PlayerPrefs.GetInt(TutorialDonePreference);
                if (Bool(args, "skip_tutorial", true)) PlayerPrefs.SetInt(TutorialDonePreference, 1);
                menu.SelectCharacter(character);
                string preset = Str(args, "preset");
                if (preset != null) menu.ApplyPreset(preset);
                if (args["settings"] is JObject settings)
                {
                    foreach (var pair in settings)
                    {
                        if (!menu.runSettings.TryGetValue(pair.Key, out object existing)) throw new Exception("unknown run setting '" + pair.Key + "'");
                        menu.runSettings[pair.Key] = Reflect.Convert(pair.Value, existing.GetType());
                    }
                }
                menu.StartRun();
                return WaitForWorld(new Dictionary<string, object> { { "character", character }, { "tutorialFlagBefore", tutorialFlagBefore } }, 90f);
            }, false,
                Arg("character", "int", "0 Experiment, 1 Milky, 2 Dune", false, 0),
                Arg("preset", "string", "Run preset name for PreRunScript.ApplyPreset, e.g. normal"),
                Arg("settings", "object", "Run setting overrides by key, e.g. {\"healingrate\": 2.0}; keys are those of PreRunScript.runSettings"),
                Arg("skip_tutorial", "bool", "Sets the didbasiccourse preference so StartRun is not blocked by the tutorial warning", false, true));

            Add("wait_state", "Waits until the game reaches a state: menu, pre-run, in-world.", args =>
            {
                string wanted = Str(args, "state", null, true);
                return new Deferred
                {
                    Waiting = "state " + wanted, TimeoutSeconds = Float(args, "timeout", 60f),
                    IsDone = () => GameState.Name() == wanted,
                    GetResult = () => new Dictionary<string, object> { { "state", GameState.Name() }, { "scene", UnityEngine.SceneManagement.SceneManager.GetActiveScene().name } },
                };
            }, false, Arg("state", "string", "menu, pre-run or in-world", true), Arg("timeout", "float", "Seconds", false, 60f));

            Add("quit_to_menu", "Leaves the current world for the main menu without saving. Completes at the menu.", args =>
            {
                if (!GameState.InWorld) throw new Exception("not in a world");
                PlayerCamera.main.ToMainMenu();
                return new Deferred
                {
                    Waiting = "main menu", TimeoutSeconds = 60f,
                    IsDone = () => PreRunScript.instance != null && !GameState.InWorld,
                    GetResult = () => new Dictionary<string, object> { { "state", GameState.Name() } },
                };
            });

            Add("save", "Writes the run save (save.sv) from the current world.", args =>
            {
                if (!GameState.InWorld) throw new Exception("not in a world");
                SaveSystem.SaveGame();
                var info = new FileInfo(GameState.SaveFilePath);
                return new Dictionary<string, object> { { "path", info.FullName }, { "bytes", info.Length }, { "writtenUtc", info.LastWriteTimeUtc.ToString("o") } };
            });

            Add("has_save", "Whether a run save exists.", args => new Dictionary<string, object> { { "hasSave", SaveSystem.HasSave() }, { "path", GameState.SaveFilePath } });

            Add("load", "From the main menu, loads the saved run. Completes when the player exists in the world.", args =>
            {
                if (PreRunScript.instance == null) throw new Exception("not at the main menu (state is " + GameState.Name() + ")");
                if (!SaveSystem.HasSave()) throw new Exception("no save file");
                if (Bool(args, "skip_tutorial", true)) PlayerPrefs.SetInt(TutorialDonePreference, 1);
                PreRunScript.instance.LoadRun();
                return WaitForWorld(new Dictionary<string, object>(), 90f);
            }, false, Arg("skip_tutorial", "bool", "Sets the didbasiccourse preference first", false, true));
        }

        private static Deferred WaitForWorld(Dictionary<string, object> carried, float timeout)
        {
            int startedAtFrame = Time.frameCount;
            return new Deferred
            {
                Waiting = "world to load", TimeoutSeconds = timeout,
                IsDone = () => Time.frameCount > startedAtFrame + 2 && GameState.InWorld && UnityEngine.SceneManagement.SceneManager.GetActiveScene().name == GameState.WorldScene,
                GetResult = () =>
                {
                    Body body = PlayerCamera.main.body;
                    carried["prefab"] = body.transform.root.name;
                    carried["position"] = Reflect.Serialize((Vector2)body.transform.position, 0);
                    carried["state"] = GameState.Name();
                    return carried;
                },
            };
        }
    }
}
