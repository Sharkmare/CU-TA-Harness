using System;
using System.Diagnostics;
using System.Runtime.CompilerServices;

namespace HookProfiler
{
    /// <summary>Per hook accumulators. Indexed arrays keep the per call cost to a few array writes.</summary>
    public static class Stats
    {
        public const int HistogramBuckets = 40;
        public const int Capacity = 8192;

        public static volatile bool Active;
        public static int MainThreadId;
        public static int Depth;
        public static long TopLevelTicks;
        public static int Count;

        public static readonly long[] Calls = new long[Capacity];
        public static readonly long[] TotalTicks = new long[Capacity];
        public static readonly long[] MaxTicks = new long[Capacity];
        public static readonly long[] TopTicks = new long[Capacity];
        public static readonly int[] BurnMicroseconds = new int[Capacity];
        public static readonly int[,] Histogram = new int[Capacity, HistogramBuckets];

        public static void Reset()
        {
            Array.Clear(Calls, 0, Capacity);
            Array.Clear(TotalTicks, 0, Capacity);
            Array.Clear(MaxTicks, 0, Capacity);
            Array.Clear(TopTicks, 0, Capacity);
            Array.Clear(Histogram, 0, Histogram.Length);
            TopLevelTicks = 0;
            Depth = 0;
        }

        public static long Enter(int index)
        {
            if (!Active || Environment.CurrentManagedThreadId != MainThreadId) return 0;
            Depth++;
            long start = Stopwatch.GetTimestamp();
            int burn = BurnMicroseconds[index];
            if (burn > 0) Spin(burn);
            return start;
        }

        public static void Exit(int index, long start)
        {
            if (start == 0) return;
            long ticks = Stopwatch.GetTimestamp() - start;
            Depth--;
            Calls[index]++;
            TotalTicks[index] += ticks;
            if (ticks > MaxTicks[index]) MaxTicks[index] = ticks;
            if (Depth == 0) { TopTicks[index] += ticks; TopLevelTicks += ticks; }
            Histogram[index, Bucket(ticks)]++;
        }

        public static int Bucket(long ticks)
        {
            int bucket = 0;
            while (ticks > 1 && bucket < HistogramBuckets - 1) { ticks >>= 1; bucket++; }
            return bucket;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void Spin(int microseconds)
        {
            long until = Stopwatch.GetTimestamp() + microseconds * Stopwatch.Frequency / 1000000;
            while (Stopwatch.GetTimestamp() < until) { }
        }
    }
}
