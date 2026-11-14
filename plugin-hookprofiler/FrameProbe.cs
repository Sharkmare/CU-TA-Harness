using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;

namespace HookProfiler
{
    /// <summary>Records one sample per rendered frame: the frame time and the mod hook time spent since the previous frame.</summary>
    public class FrameProbe : MonoBehaviour
    {
        public static bool Recording;
        public static readonly List<float> FrameSeconds = new List<float>(1 << 16);
        public static readonly List<float> HookSeconds = new List<float>(1 << 16);
        public static long FixedTicks;
        static long lastTopLevel;

        public static void Start()
        {
            FrameSeconds.Clear();
            HookSeconds.Clear();
            FixedTicks = 0;
            lastTopLevel = Stats.TopLevelTicks;
            Recording = true;
        }

        void Update()
        {
            if (!Recording) return;
            FrameSeconds.Add(Time.unscaledDeltaTime);
            long top = Stats.TopLevelTicks;
            HookSeconds.Add((float)((top - lastTopLevel) / (double)Stopwatch.Frequency));
            lastTopLevel = top;
        }

        void FixedUpdate()
        {
            if (Recording) FixedTicks++;
        }
    }
}
