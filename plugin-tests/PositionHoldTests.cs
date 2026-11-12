using System;

namespace CasualtiesLink.Tests
{
    public static class PositionHoldTests
    {
        private const int BodyId = 7;
        private const float TargetX = 10f;
        private const float TargetY = 20f;
        private const float Tolerance = 0.05f;
        private const float FallPerTick = 0.02f;
        private const float PushPerTick = 0.01f;
        private const int SimulatedTicks = 200;

        // A body that falls and is pushed a little every tick; the holder either puts it back (the real behaviour) or does nothing (the mutant).
        private static PositionHold Simulate(bool holderCorrects)
        {
            var hold = new PositionHold(BodyId, TargetX, TargetY, Tolerance);
            float x = TargetX;
            float y = TargetY;
            for (int tick = 0; tick < SimulatedTicks; tick++)
            {
                y -= FallPerTick;
                x += PushPerTick;
                bool needsCorrection = hold.Observe(x, y);
                if (needsCorrection && holderCorrects)
                {
                    x = hold.TargetX;
                    y = hold.TargetY;
                }
            }
            return hold;
        }

        private static bool Throws(Action action)
        {
            try { action(); return false; }
            catch (ArgumentException) { return true; }
        }

        public static void Register(TestSuite suite)
        {
            suite.Add("position hold: a holder that puts the body back every tick keeps the drift below the tolerance", () =>
            {
                PositionHold hold = Simulate(true);
                Check.True(hold.HeldWithinTolerance, "held");
                Check.Equal(0L, hold.ExceededTicks, "exceeded ticks");
                Check.True(hold.MaxDrift < Tolerance, "the largest drift is one tick of falling and pushing");
                Check.Equal((long)SimulatedTicks, hold.Corrections, "one correction per tick");
            });

            suite.Add("position hold: a holder that does nothing is reported as not holding (the mutant fails)", () =>
            {
                PositionHold hold = Simulate(false);
                Check.False(hold.HeldWithinTolerance, "held");
                Check.True(hold.ExceededTicks > SimulatedTicks / 2, "most ticks exceed the tolerance once the drift has built up");
                Check.True(hold.MaxDrift > FallPerTick * SimulatedTicks * 0.9f, "the body kept falling");
            });

            suite.Add("position hold: drift is the straight distance to the target", () =>
            {
                var hold = new PositionHold(BodyId, 0f, 0f, Tolerance);
                hold.Observe(3f, 4f);
                Check.Equal(5f, hold.LastDrift, "3 4 5 triangle");
            });

            suite.Add("position hold: a body exactly on target needs no correction and counts no exceeded tick", () =>
            {
                var hold = new PositionHold(BodyId, TargetX, TargetY, Tolerance);
                Check.False(hold.Observe(TargetX, TargetY), "no correction");
                Check.Equal(0L, hold.Corrections, "corrections");
                Check.Equal(1L, hold.Ticks, "ticks");
                Check.True(hold.HeldWithinTolerance, "held");
            });

            suite.Add("position hold: a drift inside the tolerance is corrected but not counted as exceeded", () =>
            {
                var hold = new PositionHold(BodyId, TargetX, TargetY, Tolerance);
                Check.True(hold.Observe(TargetX + Tolerance / 2f, TargetY), "correction");
                Check.Equal(0L, hold.ExceededTicks, "exceeded");
            });

            suite.Add("position hold: a lost body is never reported as held", () =>
            {
                var hold = new PositionHold(BodyId, TargetX, TargetY, Tolerance);
                hold.Observe(TargetX, TargetY);
                hold.Lost = true;
                Check.False(hold.HeldWithinTolerance, "lost");
            });

            suite.Add("position hold: a hold that has not been observed yet is not reported as held", () =>
            {
                Check.False(new PositionHold(BodyId, TargetX, TargetY, Tolerance).HeldWithinTolerance, "no ticks");
            });

            suite.Add("position hold: bad input is refused at the boundary", () =>
            {
                Check.True(Throws(() => new PositionHold(BodyId, float.NaN, 0f, Tolerance)), "NaN x");
                Check.True(Throws(() => new PositionHold(BodyId, 0f, float.PositiveInfinity, Tolerance)), "infinite y");
                Check.True(Throws(() => new PositionHold(BodyId, 0f, 0f, 0f)), "zero tolerance");
                Check.True(Throws(() => new PositionHold(BodyId, 0f, 0f, -1f)), "negative tolerance");
                Check.True(Throws(() => new PositionHold(BodyId, 0f, 0f, PositionHold.MaximumTolerance + 1f)), "huge tolerance");
                Check.True(Throws(() => new PositionHold(BodyId, 0f, 0f, float.NaN)), "NaN tolerance");
            });

            suite.Add("hold table: setting a body twice keeps one hold with the newest target", () =>
            {
                var table = new HoldTable();
                table.Set(BodyId, 1f, 1f, Tolerance);
                table.Set(BodyId, 2f, 3f, Tolerance);
                Check.Equal(1, table.Count, "count");
                Check.Equal(2f, table.Get(BodyId).TargetX, "target x");
                Check.Equal(3f, table.Get(BodyId).TargetY, "target y");
            });

            suite.Add("hold table: release removes one body, a repeated release reports false, clear removes all", () =>
            {
                var table = new HoldTable();
                table.Set(1, 0f, 0f, Tolerance);
                table.Set(2, 0f, 0f, Tolerance);
                Check.True(table.Remove(1), "first release");
                Check.False(table.Remove(1), "second release");
                Check.Equal(1, table.Clear(), "cleared");
                Check.Equal(0, table.Count, "empty");
                Check.True(table.Get(2) == null, "gone");
            });

            suite.Add("hold table: a snapshot can be walked while holds are changed", () =>
            {
                var table = new HoldTable();
                table.Set(1, 0f, 0f, Tolerance);
                table.Set(2, 0f, 0f, Tolerance);
                int visited = 0;
                foreach (PositionHold hold in table.Snapshot())
                {
                    table.Remove(hold.BodyId);
                    visited++;
                }
                Check.Equal(2, visited, "visited");
            });
        }
    }
}
