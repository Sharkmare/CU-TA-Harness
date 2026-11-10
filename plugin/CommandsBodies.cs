using System;
using System.Collections.Generic;
using UnityEngine;

namespace CasualtiesLink
{
    public static partial class Commands
    {
        private const string GunAngleParameter = "gunangle";

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
                    });
                }
                return rows;
            });

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
                };
            }, false, Arg("id", "int", "Instance id of a Body handle from 'bodies'"), Arg("local", "bool", "Use the local player's Body", false, false));
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
