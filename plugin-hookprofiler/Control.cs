using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using HarmonyLib;
using Newtonsoft.Json;
using UnityEngine;

namespace HookProfiler
{
    /// <summary>The surface the harness drives through the link: static methods taking and returning strings.</summary>
    public static class Control
    {
        const string HarmonyId = "hookprofiler.timing";
        static List<Hook> hooks = new List<Hook>();
        static Harmony harmony;
        static string installInfo = "{}";
        static double overheadNanoseconds;
        static Stopwatch window = new Stopwatch();
        static TimeSpan cpuAtBegin;
        static int[] collections = new int[3];
        static string label = "";

        static ISet<string> AssemblySet(string names)
        {
            return new HashSet<string>((string.IsNullOrEmpty(names) ? "CasualtiesMP" : names).Split(',').Select(n => n.Trim()).Where(n => n.Length > 0));
        }

        public static string Inventory(string assemblies)
        {
            var rows = Targets.Find(AssemblySet(assemblies)).Select(h => new { name = h.Name, kinds = h.Kinds.OrderBy(k => k).ToArray(), targets = h.Targets.OrderBy(t => t).ToArray(), il = h.IlHash, ilLength = h.IlLength });
            return JsonConvert.SerializeObject(rows);
        }

        static List<string> disabledPatches = new List<string>();
        static bool uncapped;

        /// <summary>First step, no timing wrappers yet. disable lists type name fragments whose patches are removed (the removal variant); uncap=1 turns vsync and the frame cap off so frame time measures work instead of the display.</summary>
        public static string Setup(string disable, string uncap)
        {
            Stats.MainThreadId = Environment.CurrentManagedThreadId;
            var disabled = disabledPatches;
            if (!string.IsNullOrEmpty(disable))
            {
                var fragments = disable.Split(',').Select(f => f.Trim()).Where(f => f.Length > 0).ToArray();
                var remover = new Harmony(HarmonyId + ".remove");
                foreach (var original in Harmony.GetAllPatchedMethods().ToList())
                {
                    var info = Harmony.GetPatchInfo(original);
                    if (info == null) continue;
                    foreach (var patch in info.Prefixes.Concat(info.Postfixes).Concat(info.Finalizers).Concat(info.Transpilers).ToList())
                    {
                        string owner = patch.PatchMethod.DeclaringType != null ? patch.PatchMethod.DeclaringType.FullName : "";
                        if (!fragments.Any(f => owner.Contains(f))) continue;
                        remover.Unpatch(original, patch.PatchMethod);
                        disabled.Add(owner + "." + patch.PatchMethod.Name + " on " + Targets.NameOf(original));
                    }
                }
            }
            uncapped = uncap == "1";
            if (uncapped)
            {
                QualitySettings.vSyncCount = 0;
                Application.targetFrameRate = -1;
            }
            if (UnityEngine.Object.FindObjectOfType<FrameProbe>() == null)
            {
                var host = new GameObject("HookProfilerFrames");
                UnityEngine.Object.DontDestroyOnLoad(host);
                host.AddComponent<FrameProbe>();
            }
            return JsonConvert.SerializeObject(new { disabled, uncapped });
        }

        /// <summary>Second step: wraps every hook of the named assemblies in timing. burn is "fragment:microseconds,..." (a deliberate extra cost, to prove the benchmark can fail).</summary>
        public static string Wrap(string assemblies, string burn)
        {
            if (harmony != null) return installInfo;
            hooks = Targets.Find(AssemblySet(assemblies));
            if (hooks.Count >= Stats.Capacity - 1) throw new Exception("more hooks than the profiler capacity: " + hooks.Count);
            for (int i = 0; i < hooks.Count; i++) hooks[i].Index = i;
            Stats.Count = hooks.Count;
            var burned = new List<string>();
            if (!string.IsNullOrEmpty(burn))
            {
                foreach (string rule in burn.Split(','))
                {
                    int colon = rule.LastIndexOf(':');
                    string fragment = rule.Substring(0, colon);
                    int microseconds = int.Parse(rule.Substring(colon + 1));
                    foreach (var hook in hooks.Where(h => h.Name.Contains(fragment) || h.Targets.Any(t => t.Contains(fragment))))
                    {
                        Stats.BurnMicroseconds[hook.Index] = microseconds;
                        burned.Add(hook.Name + " +" + microseconds + "us");
                    }
                }
            }
            harmony = new Harmony(HarmonyId);
            var failed = new List<string>();
            foreach (var hook in hooks)
            {
                try { Wrapper.Apply(harmony, hook); }
                catch (Exception failure) { failed.Add(hook.Name + ": " + failure.Message); hook.Index = -1; }
            }
            CalibrateOverhead();
            installInfo = JsonConvert.SerializeObject(new
            {
                hooks = hooks.Count,
                byKind = hooks.SelectMany(h => h.Kinds).GroupBy(k => k.StartsWith("unity") ? "unity" : k).ToDictionary(g => g.Key, g => g.Count()),
                disabled = disabledPatches,
                burned,
                wrapFailures = failed,
                overheadNsPerCall = Math.Round(overheadNanoseconds, 1),
                timerTickNs = 1e9 / Stopwatch.Frequency,
                uncapped,
            });
            return installInfo;
        }

        static void CalibrateOverhead()
        {
            const int calls = 2000000;
            var timer = Stopwatch.StartNew();
            int sink = 0;
            for (int i = 0; i < calls; i++) sink += Calibration.Empty(i);
            double bare = timer.Elapsed.TotalMilliseconds;
            var calibrationHook = new Hook { Name = "HookProfiler.Calibration.Empty", Method = typeof(Calibration).GetMethod(nameof(Calibration.Empty)), Index = Stats.Count };
            Stats.Count++;
            hooks.Add(calibrationHook);
            Wrapper.Apply(harmony, calibrationHook);
            Stats.Active = true;
            timer.Restart();
            for (int i = 0; i < calls; i++) sink += Calibration.Empty(i);
            double wrapped = timer.Elapsed.TotalMilliseconds;
            Stats.Active = false;
            overheadNanoseconds = (wrapped - bare) * 1e6 / calls;
            Stats.Reset();
            if (sink == 42) Console.Write("");
        }

        public static string Begin(string name)
        {
            label = name ?? "";
            Stats.Reset();
            Stats.Active = true;
            FrameProbe.Start();
            collections = new[] { GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2) };
            cpuAtBegin = Process.GetCurrentProcess().TotalProcessorTime;
            window.Restart();
            return "begun";
        }

        static double Percentile(List<float> sorted, double fraction)
        {
            if (sorted.Count == 0) return 0;
            int index = Math.Min(sorted.Count - 1, (int)Math.Ceiling(fraction * sorted.Count) - 1);
            return sorted[Math.Max(0, index)];
        }

        static object Summary(List<float> seconds)
        {
            var sorted = seconds.OrderBy(v => v).ToList();
            return new
            {
                n = sorted.Count,
                meanMs = sorted.Count == 0 ? 0 : Math.Round(sorted.Average() * 1000, 4),
                p50Ms = Math.Round(Percentile(sorted, 0.50) * 1000, 4),
                p95Ms = Math.Round(Percentile(sorted, 0.95) * 1000, 4),
                p99Ms = Math.Round(Percentile(sorted, 0.99) * 1000, 4),
                maxMs = sorted.Count == 0 ? 0 : Math.Round(sorted.Last() * 1000, 4),
            };
        }

        static double HistogramUpperMicroseconds(int index, double fraction)
        {
            long total = 0;
            for (int b = 0; b < Stats.HistogramBuckets; b++) total += Stats.Histogram[index, b];
            if (total == 0) return 0;
            long target = (long)Math.Ceiling(fraction * total), running = 0;
            for (int b = 0; b < Stats.HistogramBuckets; b++)
            {
                running += Stats.Histogram[index, b];
                if (running >= target) return Math.Pow(2, b + 1) * 1e6 / Stopwatch.Frequency;
            }
            return 0;
        }

        public static string End()
        {
            Stats.Active = false;
            FrameProbe.Recording = false;
            window.Stop();
            double wall = window.Elapsed.TotalSeconds;
            double cpu = (Process.GetCurrentProcess().TotalProcessorTime - cpuAtBegin).TotalSeconds;
            double ms = 1000.0 / Stopwatch.Frequency;
            int frames = FrameProbe.FrameSeconds.Count;
            var rows = new List<KeyValuePair<double, object>>();
            foreach (var hook in hooks)
            {
                if (hook.Index < 0) continue;
                long calls = Stats.Calls[hook.Index];
                if (calls == 0) continue;
                double totalMs = Stats.TotalTicks[hook.Index] * ms;
                rows.Add(new KeyValuePair<double, object>(totalMs, new
                {
                    name = hook.Name,
                    kinds = hook.Kinds.OrderBy(k => k).ToArray(),
                    targets = hook.Targets.OrderBy(t => t).Take(4).ToArray(),
                    calls,
                    totalMs = Math.Round(totalMs, 4),
                    topLevelMs = Math.Round(Stats.TopTicks[hook.Index] * ms, 4),
                    meanUs = Math.Round(totalMs * 1000 / calls, 3),
                    netMeanUs = Math.Round(Math.Max(0, totalMs * 1000 / calls - overheadNanoseconds / 1000), 3),
                    p95Us = Math.Round(HistogramUpperMicroseconds(hook.Index, 0.95), 2),
                    p99Us = Math.Round(HistogramUpperMicroseconds(hook.Index, 0.99), 2),
                    maxUs = Math.Round(Stats.MaxTicks[hook.Index] * ms * 1000, 2),
                    callsPerFrame = frames == 0 ? 0 : Math.Round(calls / (double)frames, 3),
                    callsPerFixedTick = FrameProbe.FixedTicks == 0 ? 0 : Math.Round(calls / (double)FrameProbe.FixedTicks, 3),
                }));
            }
            var report = new
            {
                label,
                wallSeconds = Math.Round(wall, 3),
                frames = Summary(FrameProbe.FrameSeconds),
                hookSecondsPerFrame = Summary(FrameProbe.HookSeconds),
                fixedTicks = FrameProbe.FixedTicks,
                cpuSeconds = Math.Round(cpu, 3),
                processCpuShareOfOneCore = wall == 0 ? 0 : Math.Round(cpu / wall, 4),
                hookTopLevelShareOfWall = wall == 0 ? 0 : Math.Round(Stats.TopLevelTicks / (double)Stopwatch.Frequency / wall, 5),
                gcCollections = new { gen0 = GC.CollectionCount(0) - collections[0], gen1 = GC.CollectionCount(1) - collections[1], gen2 = GC.CollectionCount(2) - collections[2] },
                overheadNsPerCall = Math.Round(overheadNanoseconds, 1),
                hooks = rows.OrderByDescending(r => r.Key).Select(r => r.Value).ToList(),
            };
            return JsonConvert.SerializeObject(report);
        }
    }
}
