using System;
using System.Collections.Generic;
using UnityEngine;

namespace CasualtiesLink
{
    public static partial class Commands
    {
        private const string GunAngleParameter = "gunangle";
        private const float DefaultHoldTolerance = 0.05f;

        private static void RegisterBodies()
        {
            Add("bodies", "Lists every Body in the world with its handle, charType, root object name and whether it is the local player.", args =>
            {
                Body local = GameState.InWorld ? PlayerCamera.main.body : null;
                var rows = new List<object>();
                foreach (Body body in UnityEngine.Object.FindObjectsOfType<Body>())
                {
                    rows.Add(new Dictionary<string, object>
                    {
                        { "object", Reflect.Handle(body) }, { "charType", body.charType },
                        { "root", body.transform.root.name }, { "local", body == local },
                        { "active", body.gameObject.activeInHierarchy }, { "parent", body.transform.parent != null ? body.transform.parent.name : null },
                    });
                }
                return rows;
            });

            RegisterHolds();

            Add("body_visuals", "Sprite names, limb child names, limb angles and the arms animator gunangle of one Body, for comparing how a player looks on different instances.", args =>
            {
                Body body = BodyFromArguments(args);
                Transform root = body.transform.root;
                var sprites = new List<object>();
                foreach (SpriteRenderer renderer in root.GetComponentsInChildren<SpriteRenderer>(true))
                {
                    sprites.Add(new Dictionary<string, object>
                    {
                        { "path", RelativePath(renderer.transform, root) },
                        { "sprite", renderer.sprite != null ? renderer.sprite.name : null },
                    });
                }
                var limbs = new List<object>();
                for (int i = 0; i < body.limbs.Length; i++)
                {
                    Transform limbTransform = body.limbs[i].transform;
                    var children = new List<string>();
                    foreach (Transform child in limbTransform) children.Add(child.name);
                    limbs.Add(new Dictionary<string, object>
                    {
                        { "index", i }, { "name", body.limbs[i].name }, { "children", children },
                        { "angle", limbTransform.eulerAngles.z }, { "localAngle", limbTransform.localEulerAngles.z },
                    });
                }
                return new Dictionary<string, object>
                {
                    { "root", root.name }, { "charType", body.charType }, { "sprites", sprites }, { "limbs", limbs },
                    { "gunangle", body.armsAnimator != null ? (object)body.armsAnimator.GetFloat(GunAngleParameter) : null },
                    { "bodyController", ControllerName(body.bodyAnimator) }, { "armsController", ControllerName(body.armsAnimator) },
                    { "bodyAnimatorId", AnimatorId(body.bodyAnimator) }, { "armsAnimatorId", AnimatorId(body.armsAnimator) },
                    { "bodyAnimatorPath", AnimatorPath(body.bodyAnimator, root) }, { "armsAnimatorPath", AnimatorPath(body.armsAnimator, root) },
                };
            }, false, Arg("id", "int", "Instance id of a Body handle from 'bodies'"), Arg("local", "bool", "Use the local player's Body", false, false));
        }

        private static void RegisterHolds()
        {
            Add("hold_body", "Holds one Body at an exact position: every physics tick and before every frame the position is put back and every velocity under the body is zeroed, so it cannot drift, be pushed or fall. Returns the hold status.", args =>
            {
                Body body = BodyFromArguments(args);
                BodyHoldDriver.EnsureInstalled();
                PositionHold hold = BodyHoldDriver.Table.Set(body.GetInstanceID(), Float(args, "x", float.NaN), Float(args, "y", float.NaN), Float(args, "tolerance", DefaultHoldTolerance));
                BodyHoldDriver.Apply(false);
                return BodyHoldDriver.Describe(hold);
            }, false, Arg("id", "int", "Instance id of a Body handle from 'bodies'"), Arg("local", "bool", "Hold the local player's Body", false, false),
                Arg("x", "float", "Target x", true), Arg("y", "float", "Target y", true), Arg("tolerance", "float", "Allowed drift before a tick counts as exceeded", false, DefaultHoldTolerance));

            Add("release_body", "Releases the hold on one Body (id or local), or on every held Body with all=true. Returns how many holds were removed.", args =>
            {
                if (Bool(args, "all", false)) return new Dictionary<string, object> { { "released", BodyHoldDriver.Table.Clear() } };
                Body body = BodyFromArguments(args);
                return new Dictionary<string, object> { { "released", BodyHoldDriver.Table.Remove(body.GetInstanceID()) ? 1 : 0 } };
            }, false, Arg("id", "int", "Instance id of a Body handle from 'bodies'"), Arg("local", "bool", "Release the local player's Body", false, false), Arg("all", "bool", "Release every hold", false, false));

            Add("hold_status", "Status of every active hold: target, current position, drift now, the largest drift seen before a correction, how many ticks exceeded the tolerance, and whether the body is still found.", args =>
            {
                var rows = new List<object>();
                foreach (PositionHold hold in BodyHoldDriver.Table.Snapshot()) rows.Add(BodyHoldDriver.Describe(hold));
                return rows;
            });
        }

        private static Body BodyFromArguments(Newtonsoft.Json.Linq.JObject args)
        {
            if (Bool(args, "local", false))
            {
                if (!GameState.InWorld) throw new Exception("not in a world");
                return PlayerCamera.main.body;
            }
            string id = args["id"] != null ? args["id"].ToString() : throw new Exception("give 'id' or 'local'");
            Body body = Reflect.ResolveTarget("id:" + id, out _) as Body;
            if (body == null) throw new Exception("id " + id + " is not a Body");
            return body;
        }

        private static object AnimatorId(Animator animator)
        {
            return animator != null ? (object)animator.GetInstanceID() : null;
        }

        private static string AnimatorPath(Animator animator, Transform root)
        {
            if (animator == null) return null;
            return animator.transform.IsChildOf(root) ? RelativePath(animator.transform, root) : "<outside " + root.name + ">";
        }

        private static string ControllerName(Animator animator)
        {
            return animator != null && animator.runtimeAnimatorController != null ? animator.runtimeAnimatorController.name : null;
        }

        private static string RelativePath(Transform transform, Transform root)
        {
            var parts = new List<string>();
            for (Transform current = transform; current != null && current != root; current = current.parent) parts.Insert(0, current.name);
            return string.Join("/", parts);
        }
    }
}
