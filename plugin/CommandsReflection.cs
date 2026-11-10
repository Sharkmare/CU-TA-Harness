using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CasualtiesLink
{
    public static partial class Commands
    {
        private static void RegisterReflection()
        {
            Add("find", "Finds live objects by component type and/or GameObject name and returns handles usable as id:N targets.", args =>
            {
                string typeName = Str(args, "type");
                string nameContains = Str(args, "name");
                int limit = Int(args, "limit", 50);
                if (typeName == null && nameContains == null) throw new Exception("give 'type' or 'name'");
                IEnumerable<UnityEngine.Object> candidates = typeName != null
                    ? UnityEngine.Object.FindObjectsOfType(Reflect.FindType(typeName))
                    : UnityEngine.Object.FindObjectsOfType<GameObject>();
                var rows = new List<object>();
                foreach (var obj in candidates)
                {
                    if (nameContains != null && obj.name.IndexOf(nameContains, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    Transform transform = obj is Component c ? c.transform : (obj as GameObject)?.transform;
                    var row = new Dictionary<string, object> { { "object", Reflect.Handle(obj) } };
                    if (transform != null) row["position"] = Reflect.Serialize((Vector2)transform.position, 0);
                    rows.Add(row);
                    if (rows.Count >= limit) break;
                }
                return rows;
            }, false, Arg("type", "string", "Component type name, e.g. Item"), Arg("name", "string", "GameObject name substring"), Arg("limit", "int", "Maximum rows", false, 50));

            Add("get", "Reads a value by path. Target: player, camera, world, console, static:Type, type:Type[#n], name:GameObject, id:N. Path example: limbs[3].bleedAmount.", args =>
                Reflect.Read(Str(args, "target", null, true), Str(args, "path", ""), Int(args, "depth", 1), Bool(args, "nonpublic", false)), false,
                Arg("target", "string", "Object selector", true), Arg("path", "string", "Dotted path with [index] steps; empty reads the target itself"),
                Arg("depth", "int", "How many levels of object fields to expand", false, 1), Arg("nonpublic", "bool", "Allow non public members", false, false));

            Add("set", "Writes a value by path (same target and path rules as get). Values convert to the field type: numbers, bools, strings, enums by name, Vector2/3 as {x,y,z}, object references as 'id:N'.", args =>
                Reflect.Write(Str(args, "target", null, true), Str(args, "path", null, true), args["value"] ?? throw new Exception("argument 'value' is required"), Bool(args, "nonpublic", false)), false,
                Arg("target", "string", "Object selector", true), Arg("path", "string", "Path to the field", true),
                Arg("value", "any", "New value as JSON", true), Arg("nonpublic", "bool", "Allow non public members", false, false));
        }
    }
}
