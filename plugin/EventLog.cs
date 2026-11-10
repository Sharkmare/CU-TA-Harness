using System;
using System.Collections.Generic;
using System.Threading;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CasualtiesLink
{
    public static class EventLog
    {
        private const int MaxEvents = 5000;
        private const int MaxLogLines = 3000;
        private const float DamageEpsilon = 0.01f;

        private static readonly object Gate = new object();
        private static readonly EventBuffer Buffer = new EventBuffer(MaxEvents, () => Clock.Elapsed.TotalSeconds);
        private static readonly List<Dictionary<string, object>> LogLines = new List<Dictionary<string, object>>();
        private static readonly System.Diagnostics.Stopwatch Clock = System.Diagnostics.Stopwatch.StartNew();
        private static long nextLogSeq = 1;

        private static Body trackedBody;
        private static bool trackedAlive;
        private static float[] trackedLimbHealth;

        public static List<string> ConsoleCapture;

        public static void Install()
        {
            Application.logMessageReceived += OnUnityLog;
            SceneManager.activeSceneChanged += (from, to) => Emit("scene_changed", new Dictionary<string, object> { { "from", from.name }, { "to", to.name } });
            Emit("link_started", new Dictionary<string, object> { { "version", Plugin.Version } });
        }

        public static long Emit(string type, Dictionary<string, object> data)
        {
            return Buffer.Emit(type, data, MainThread.FrameNumber);
        }

        public static long LastSequence
        {
            get { return Buffer.LastSequence; }
        }

        public static object Read(long since, int waitMilliseconds, int limit, string type)
        {
            return Buffer.Read(since, waitMilliseconds, limit, type);
        }

        public static object ReadLog(long since, int tail, string contains)
        {
            lock (Gate)
            {
                var chosen = new List<Dictionary<string, object>>();
                foreach (var line in LogLines)
                {
                    if ((long)line["seq"] <= since) continue;
                    if (contains != null && ((string)line["text"]).IndexOf(contains, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    chosen.Add(line);
                }
                if (tail > 0 && chosen.Count > tail) chosen.RemoveRange(0, chosen.Count - tail);
                return new Dictionary<string, object> { { "lines", chosen }, { "last", nextLogSeq - 1 } };
            }
        }

        private static void OnUnityLog(string condition, string stackTrace, LogType type)
        {
            lock (Gate)
            {
                var line = new Dictionary<string, object> { { "seq", nextLogSeq++ }, { "level", type.ToString() }, { "text", condition } };
                if (type == LogType.Exception || type == LogType.Error) line["stack"] = stackTrace;
                LogLines.Add(line);
                if (LogLines.Count > MaxLogLines) LogLines.RemoveRange(0, LogLines.Count - MaxLogLines);
            }
            if (type == LogType.Exception || type == LogType.Error)
                Emit("exception", new Dictionary<string, object> { { "level", type.ToString() }, { "message", condition }, { "stack", stackTrace } });
        }

        public static void PollGameState()
        {
            Body body = PlayerCamera.main != null ? PlayerCamera.main.body : null;
            if (body == null) { trackedBody = null; return; }
            if (body != trackedBody)
            {
                trackedBody = body;
                trackedAlive = body.alive;
                trackedLimbHealth = new float[body.limbs.Length];
                for (int i = 0; i < body.limbs.Length; i++) trackedLimbHealth[i] = LimbHealth(body.limbs[i]);
                Emit("player_ready", new Dictionary<string, object> { { "prefab", body.transform.root.name } });
                return;
            }
            for (int i = 0; i < body.limbs.Length && i < trackedLimbHealth.Length; i++)
            {
                float now = LimbHealth(body.limbs[i]);
                float drop = trackedLimbHealth[i] - now;
                if (drop > DamageEpsilon)
                    Emit("damage", new Dictionary<string, object> { { "limb", body.limbs[i].name }, { "index", i }, { "amount", drop }, { "health", now } });
                trackedLimbHealth[i] = now;
            }
            if (trackedAlive && !body.alive) Emit("death", new Dictionary<string, object> { { "brainHealth", body.brainHealth } });
            trackedAlive = body.alive;
        }

        private static float LimbHealth(Limb limb) { return limb.skinHealth + limb.muscleHealth; }
    }

    [HarmonyPatch(typeof(ConsoleScript), "LogToConsole")]
    public static class ConsoleLogPatch
    {
        private static void Postfix(string text)
        {
            if (EventLog.ConsoleCapture != null) EventLog.ConsoleCapture.Add(text);
            EventLog.Emit("console", new Dictionary<string, object> { { "text", text } });
        }
    }

    [HarmonyPatch(typeof(Body), nameof(Body.PickUpItem))]
    public static class PickUpPatch
    {
        private static void Postfix(Body __instance, Item item, int slot)
        {
            if (item == null || __instance != PlayerCamera.main?.body) return;
            if (__instance.SlotOf(item) < 0) return;
            EventLog.Emit("item_picked_up", new Dictionary<string, object> { { "id", item.id }, { "slot", slot }, { "condition", item.condition } });
        }
    }
}
