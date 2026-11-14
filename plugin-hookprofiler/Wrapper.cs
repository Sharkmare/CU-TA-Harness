using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using HarmonyLib;

namespace HookProfiler
{
    /// <summary>The timing patch applied to every hook body. The hook is found from the patched method handle so one static pair serves all hooks.</summary>
    public static class Wrapper
    {
        public static readonly Dictionary<long, int> IndexByHandle = new Dictionary<long, int>();

        public static void Pre(out long __state, MethodBase __originalMethod)
        {
            __state = 0;
            if (!Stats.Active) return;
            if (IndexByHandle.TryGetValue((long)__originalMethod.MethodHandle.Value, out int index)) __state = Stats.Enter(index);
        }

        public static void Fin(long __state, MethodBase __originalMethod)
        {
            if (__state == 0) return;
            if (IndexByHandle.TryGetValue((long)__originalMethod.MethodHandle.Value, out int index)) Stats.Exit(index, __state);
        }

        public static void Apply(Harmony harmony, Hook hook)
        {
            IndexByHandle[(long)hook.Method.MethodHandle.Value] = hook.Index;
            harmony.Patch(hook.Method,
                prefix: new HarmonyMethod(typeof(Wrapper).GetMethod(nameof(Pre))) { priority = Priority.First },
                finalizer: new HarmonyMethod(typeof(Wrapper).GetMethod(nameof(Fin))) { priority = Priority.Last });
        }
    }

    public static class Calibration
    {
        [MethodImpl(MethodImplOptions.NoInlining)]
        public static int Empty(int value) { return value + 1; }
    }
}
