using System.Collections.Generic;
using UnityEngine;

namespace CasualtiesLink
{
    /// <summary>Re-asserts held body positions on every physics tick and before every frame is drawn, and zeroes every velocity under the body.</summary>
    public class BodyHoldDriver : MonoBehaviour
    {
        public static readonly HoldTable Table = new HoldTable();
        private static BodyHoldDriver instance;

        public static void EnsureInstalled()
        {
            if (instance != null) return;
            instance = MainThread.Instance.gameObject.AddComponent<BodyHoldDriver>();
        }

        private void FixedUpdate() { Apply(true); }

        private void LateUpdate() { Apply(false); }

        public static void Apply(bool observe)
        {
            foreach (PositionHold hold in Table.Snapshot())
            {
                Body body = Reflect.ResolveTarget("id:" + hold.BodyId, out _) as Body;
                if (body == null)
                {
                    hold.Lost = true;
                    continue;
                }
                Vector3 position = body.transform.position;
                bool needsCorrection = observe ? hold.Observe(position.x, position.y) : PositionHold.Distance(position.x, position.y, hold.TargetX, hold.TargetY) > 0f;
                if (needsCorrection) body.transform.position = new Vector3(hold.TargetX, hold.TargetY, position.z);
                StopMotion(body);
            }
        }

        private static void StopMotion(Body body)
        {
            foreach (Rigidbody2D rigidbody in body.GetComponentsInChildren<Rigidbody2D>(true))
            {
                rigidbody.velocity = Vector2.zero;
                rigidbody.angularVelocity = 0f;
            }
        }

        public static Dictionary<string, object> Describe(PositionHold hold)
        {
            Body body = Reflect.ResolveTarget("id:" + hold.BodyId, out _) as Body;
            Vector3 position = body != null ? body.transform.position : Vector3.zero;
            return new Dictionary<string, object>
            {
                { "id", hold.BodyId }, { "target", new Dictionary<string, object> { { "x", hold.TargetX }, { "y", hold.TargetY } } }, { "tolerance", hold.Tolerance },
                { "position", body != null ? new Dictionary<string, object> { { "x", position.x }, { "y", position.y } } : null },
                { "drift", body != null ? (object)PositionHold.Distance(position.x, position.y, hold.TargetX, hold.TargetY) : null },
                { "ticks", hold.Ticks }, { "corrections", hold.Corrections }, { "exceededTicks", hold.ExceededTicks }, { "maxDrift", hold.MaxDrift }, { "lastDrift", hold.LastDrift },
                { "lost", hold.Lost }, { "heldWithinTolerance", hold.HeldWithinTolerance },
            };
        }
    }
}
