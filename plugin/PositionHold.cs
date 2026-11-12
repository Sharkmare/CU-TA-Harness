using System;
using System.Collections.Generic;

namespace CasualtiesLink
{
    /// <summary>Where one body is held and what the holder saw: no Unity types, so the plugin tests can run it.</summary>
    public sealed class PositionHold
    {
        public const float MinimumTolerance = 0.001f;
        public const float MaximumTolerance = 5f;

        public readonly int BodyId;
        public readonly float TargetX;
        public readonly float TargetY;
        public readonly float Tolerance;
        public long Ticks;
        public long ExceededTicks;
        public long Corrections;
        public float MaxDrift;
        public float LastDrift;
        public bool Lost;

        public PositionHold(int bodyId, float targetX, float targetY, float tolerance)
        {
            if (!IsFinite(targetX) || !IsFinite(targetY)) throw new ArgumentException("the target position must be finite");
            if (!IsFinite(tolerance) || tolerance < MinimumTolerance || tolerance > MaximumTolerance)
                throw new ArgumentException("tolerance must be between " + MinimumTolerance + " and " + MaximumTolerance);
            BodyId = bodyId;
            TargetX = targetX;
            TargetY = targetY;
            Tolerance = tolerance;
        }

        public static bool IsFinite(float value) { return !float.IsNaN(value) && !float.IsInfinity(value); }

        public static float Distance(float ax, float ay, float bx, float by)
        {
            float dx = ax - bx;
            float dy = ay - by;
            return (float)Math.Sqrt(dx * dx + dy * dy);
        }

        /// <summary>Records how far the body is from its target before the holder corrects it; true when a correction is needed.</summary>
        public bool Observe(float x, float y)
        {
            float drift = Distance(x, y, TargetX, TargetY);
            Ticks++;
            LastDrift = drift;
            if (drift > MaxDrift) MaxDrift = drift;
            if (drift > Tolerance) ExceededTicks++;
            bool needsCorrection = drift > 0f;
            if (needsCorrection) Corrections++;
            return needsCorrection;
        }

        public bool HeldWithinTolerance { get { return !Lost && Ticks > 0 && ExceededTicks == 0; } }
    }

    public sealed class HoldTable
    {
        private readonly Dictionary<int, PositionHold> holds = new Dictionary<int, PositionHold>();

        public int Count { get { return holds.Count; } }

        public PositionHold Set(int bodyId, float x, float y, float tolerance)
        {
            var hold = new PositionHold(bodyId, x, y, tolerance);
            holds[bodyId] = hold;
            return hold;
        }

        public bool Remove(int bodyId) { return holds.Remove(bodyId); }

        public int Clear()
        {
            int count = holds.Count;
            holds.Clear();
            return count;
        }

        public PositionHold Get(int bodyId)
        {
            PositionHold hold;
            return holds.TryGetValue(bodyId, out hold) ? hold : null;
        }

        public List<PositionHold> Snapshot() { return new List<PositionHold>(holds.Values); }
    }
}
