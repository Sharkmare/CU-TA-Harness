using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CasualtiesLink
{
    public static class GameState
    {
        public const string MenuScene = "PreGen";
        public const string WorldScene = "SampleScene";

        public static bool InWorld { get { return PlayerCamera.main != null && PlayerCamera.main.body != null && WorldGeneration.world != null; } }

        public static string Name()
        {
            if (InWorld) return "in-world";
            if (PreRunScript.instance != null)
                return PreRunScript.instance.runSettingsScreen != null && PreRunScript.instance.runSettingsScreen.activeSelf ? "pre-run" : "menu";
            return "loading";
        }

        public static string SaveFilePath { get { return Application.persistentDataPath + "\\save.sv"; } }
    }

    public static partial class Commands
    {
        private static void RegisterCore()
        {
            Add("status", "Plugin version, protocol, process id, scene, state and frame counters.", args => new Dictionary<string, object>
            {
                { "plugin", "CasualtiesLink" }, { "version", Plugin.Version }, { "protocol", Plugin.ProtocolVersion },
                { "port", Plugin.BoundPort }, { "pid", System.Diagnostics.Process.GetCurrentProcess().Id },
                { "scene", SceneManager.GetActiveScene().name }, { "state", GameState.Name() },
                { "frame", Time.frameCount }, { "timeScale", Time.timeScale }, { "uptime", Time.realtimeSinceStartup },
                { "gameVersion", Application.version }, { "unity", Application.unityVersion },
                { "lastEvent", EventLog.LastSequence }, { "persistentDataPath", Application.persistentDataPath },
                { "commandLine", Environment.GetCommandLineArgs() },
            });

            Add("describe_type", "Lists the public fields and properties of a game or Unity type, for building get and set paths.",
                args => Reflect.DescribeType(Str(args, "type", null, true)), false,
                Arg("type", "string", "Type name, e.g. Body or UnityEngine.Rigidbody2D", true));

            Add("state", "Scene, high level state and a short summary of the current world.", args =>
            {
                var summary = new Dictionary<string, object> { { "scene", SceneManager.GetActiveScene().name }, { "state", GameState.Name() } };
                if (GameState.InWorld)
                {
                    Body body = PlayerCamera.main.body;
                    summary["prefab"] = body.transform.root.name;
                    summary["alive"] = body.alive;
                    summary["depth"] = WorldGeneration.world.biomeDepth;
                    summary["position"] = Reflect.Serialize((Vector2)body.transform.position, 0);
                    summary["character"] = PreRunScript.characterSelected;
                }
                return summary;
            });

            Add("timescale", "Sets Time.timeScale. 0 pauses the simulation; commands still run.", args =>
            {
                Time.timeScale = Mathf.Max(0f, Float(args, "value", 1f));
                return new Dictionary<string, object> { { "timeScale", Time.timeScale } };
            }, false, Arg("value", "float", "New time scale, 0 or more", true));

            Add("step", "Advances N frames while paused (timeScale 0), then pauses again. If the game is running it just waits N frames.", args =>
            {
                int frames = Math.Max(1, Int(args, "frames", 1));
                float stepScale = Float(args, "timescale", 1f);
                bool wasPaused = Time.timeScale == 0f;
                if (wasPaused) Time.timeScale = stepScale;
                int target = Time.frameCount + frames;
                return new Deferred
                {
                    Waiting = "frames",
                    TimeoutSeconds = 30f + frames / 20f,
                    IsDone = () => Time.frameCount >= target,
                    GetResult = () =>
                    {
                        if (wasPaused) Time.timeScale = 0f;
                        return new Dictionary<string, object> { { "frame", Time.frameCount }, { "stepped", frames } };
                    },
                };
            }, false, Arg("frames", "int", "Frames to advance", false, 1), Arg("timescale", "float", "Time scale used while stepping when paused", false, 1f));

            Add("log", "Unity log lines (Debug.Log, warnings, errors, exceptions) from the plugin's buffer.", args =>
                EventLog.ReadLog(Int(args, "since", 0), Int(args, "tail", 100), Str(args, "contains")), true,
                Arg("since", "int", "Only lines with sequence above this", false, 0), Arg("tail", "int", "Keep the last N lines", false, 100),
                Arg("contains", "string", "Case insensitive substring filter"));

            Add("screenshot", "Saves the game view to a PNG and returns its path and size.", args =>
            {
                string path = Str(args, "path") ?? Path.Combine(Path.GetTempPath(), "casualtieslink_" + Time.frameCount + ".png");
                var box = new Dictionary<string, object>();
                bool done = false;
                MainThread.Instance.StartCoroutine(CaptureAfterFrame(path, box, () => done = true));
                return new Deferred { Waiting = "screenshot", TimeoutSeconds = 20f, IsDone = () => done, GetResult = () => box };
            }, false, Arg("path", "string", "Output file; defaults to the temp folder"));

            Add("console", "Runs one game console command (cheats allowed). Returns the console lines it produced.", args =>
            {
                string line = Str(args, "line", null, true).Trim();
                return RunConsole(line, Bool(args, "keep_open", false));
            }, false, Arg("line", "string", "Command line, e.g. 'spawn bandage' or 'heal'", true),
                Arg("keep_open", "bool", "Leave the console window open if the command opened it. Cheat commands open it, and an open console blocks gameplay input, so it is closed by default.", false, false));

            Add("console_log", "The game's own console history (last 100 lines).", args =>
            {
                ConsoleScript.CheckForConsole();
                int tail = Int(args, "tail", 30);
                var lines = ConsoleScript.instance.logs;
                return lines.GetRange(Math.Max(0, lines.Count - tail), Math.Min(tail, lines.Count));
            }, false, Arg("tail", "int", "Lines to return", false, 30));

            Add("game_commands", "Names, descriptions and arguments of the game's own console commands.", args =>
            {
                ConsoleScript.CheckForConsole();
                var list = new List<object>();
                foreach (var command in ConsoleScript.Commands)
                    list.Add(new Dictionary<string, object> { { "name", command.name }, { "description", command.description }, { "usage", command.GetShortDescription() } });
                return list;
            });

            Add("quit", "Closes the game shortly after replying.", args =>
            {
                MainThread.Instance.StartCoroutine(QuitSoon());
                return new Dictionary<string, object> { { "quitting", true } };
            });
        }

        private static IEnumerator QuitSoon()
        {
            yield return new WaitForSecondsRealtime(0.5f);
            Application.Quit();
        }

        private static IEnumerator CaptureAfterFrame(string path, Dictionary<string, object> box, Action finished)
        {
            yield return new WaitForEndOfFrame();
            try
            {
                Texture2D texture = ScreenCapture.CaptureScreenshotAsTexture();
                byte[] png = texture.EncodeToPNG();
                UnityEngine.Object.Destroy(texture);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
                File.WriteAllBytes(path, png);
                box["path"] = Path.GetFullPath(path);
                box["width"] = Screen.width;
                box["height"] = Screen.height;
                box["bytes"] = png.Length;
            }
            catch (Exception ex) { box["error"] = ex.Message; }
            finished();
        }

        private static object RunConsole(string line, bool keepOpen)
        {
            ConsoleScript.CheckForConsole();
            if (ConsoleScript.instance == null) throw new Exception("console could not be created");
            bool wasActive = ConsoleScript.instance.active;
            string[] words = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
            var captured = new List<string>();
            EventLog.ConsoleCapture = captured;
            try
            {
                MethodInfo run = typeof(ConsoleScript).GetMethod("TryExecuteCommand", BindingFlags.Instance | BindingFlags.NonPublic);
                run.Invoke(ConsoleScript.instance, new object[] { words, false });
            }
            finally { EventLog.ConsoleCapture = null; }
            if (!wasActive && !keepOpen && ConsoleScript.instance.active) ConsoleScript.instance.ToggleActiveState();
            bool failed = captured.Exists(l => l.Contains("failed:") || l.Contains("Invalid command"));
            return new Dictionary<string, object> { { "line", line }, { "output", captured }, { "failed", failed } };
        }
    }
}
