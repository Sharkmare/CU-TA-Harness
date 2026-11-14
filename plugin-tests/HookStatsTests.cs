using System;
using System.Diagnostics;
using System.Threading;
using HookProfiler;

namespace CasualtiesLink.Tests
{
    public static class HookStatsTests
    {
        static void Fresh()
        {
            Stats.Active = true;
            Stats.MainThreadId = Environment.CurrentManagedThreadId;
            Array.Clear(Stats.BurnMicroseconds, 0, Stats.Capacity);
            Stats.Reset();
        }

        public static void Register(TestSuite suite)
        {
            suite.Add("hook stats: buckets are powers of two", () =>
            {
                Check.Equal(0, Stats.Bucket(0));
                Check.Equal(0, Stats.Bucket(1));
                Check.Equal(1, Stats.Bucket(2));
                Check.Equal(1, Stats.Bucket(3));
                Check.Equal(2, Stats.Bucket(4));
                Check.Equal(10, Stats.Bucket(1024));
                Check.Equal(Stats.HistogramBuckets - 1, Stats.Bucket(long.MaxValue));
            });

            suite.Add("hook stats: a call is counted and timed", () =>
            {
                Fresh();
                long start = Stats.Enter(3);
                Stats.Spin(500);
                Stats.Exit(3, start);
                Check.Equal(1L, Stats.Calls[3]);
                Check.True(Stats.TotalTicks[3] >= 500L * Stopwatch.Frequency / 1000000, "the recorded time covers the 500 microsecond spin");
                Check.Equal(Stats.TotalTicks[3], Stats.TopTicks[3], "a call with nothing around it is top level");
                Check.Equal(0L, Stats.Calls[4]);
            });

            suite.Add("hook stats: a nested call is not top level", () =>
            {
                Fresh();
                long outer = Stats.Enter(1);
                long inner = Stats.Enter(2);
                Stats.Spin(200);
                Stats.Exit(2, inner);
                Stats.Exit(1, outer);
                Check.Equal(0L, Stats.TopTicks[2], "inner hook adds no top level time");
                Check.Equal(Stats.TotalTicks[1], Stats.TopTicks[1], "outer hook is top level");
                Check.Equal(Stats.TopTicks[1], Stats.TopLevelTicks, "top level total is the outer time only");
                Check.Equal(0, Stats.Depth, "depth returns to zero");
            });

            suite.Add("hook stats: nothing is recorded while inactive", () =>
            {
                Fresh();
                Stats.Active = false;
                long start = Stats.Enter(5);
                Check.Equal(0L, start, "no timestamp is taken");
                Stats.Exit(5, start);
                Check.Equal(0L, Stats.Calls[5]);
            });

            suite.Add("hook stats: calls from another thread are ignored", () =>
            {
                Fresh();
                long other = -1;
                var thread = new Thread(() => { other = Stats.Enter(6); });
                thread.Start();
                thread.Join();
                Check.Equal(0L, other, "a hook running off the main thread is skipped");
                Check.Equal(0, Stats.Depth);
            });

            suite.Add("hook stats: a burn is part of the measured time", () =>
            {
                Fresh();
                Stats.BurnMicroseconds[7] = 2000;
                long start = Stats.Enter(7);
                Stats.Exit(7, start);
                Check.True(Stats.TotalTicks[7] >= 2000L * Stopwatch.Frequency / 1000000, "the 2 millisecond burn shows in the hook total");
                Check.Equal(0L, Stats.TotalTicks[8]);
            });

            suite.Add("hook stats: a histogram bucket is filled per call", () =>
            {
                Fresh();
                long start = Stats.Enter(9);
                Stats.Spin(300);
                Stats.Exit(9, start);
                int filled = 0;
                for (int bucket = 0; bucket < Stats.HistogramBuckets; bucket++) filled += Stats.Histogram[9, bucket];
                Check.Equal(1, filled);
            });
        }
    }
}
