using System;
using System.Collections.Generic;
using System.Linq;
using Mono.Cecil;

namespace IlCost
{
    public class HookEntry
    {
        public string Name;
        public string Kind;
        public string Target;
        public string Trigger;
        public MethodDefinition Method;
    }

    /// <summary>Finds the entry points the game calls by itself, from the compiled attributes and base types.</summary>
    public static class Hooks
    {
        static readonly string[] UnityMessages = { "Update", "FixedUpdate", "LateUpdate", "OnGUI", "OnCollisionEnter2D", "OnCollisionStay2D", "OnCollisionExit2D", "OnTriggerEnter2D", "OnTriggerStay2D", "OnTriggerExit2D" };
        static readonly string[] PatchMethodNames = { "Prefix", "Postfix", "Finalizer" };

        public static string TriggerOf(string targetMethodName)
        {
            if (targetMethodName == null) return "call";
            if (targetMethodName.StartsWith("OnCollision", StringComparison.Ordinal) || targetMethodName.StartsWith("OnTrigger", StringComparison.Ordinal)) return "collision";
            if (targetMethodName == "FixedUpdate") return "physics tick";
            if (targetMethodName == "Update" || targetMethodName == "LateUpdate" || targetMethodName == "OnGUI") return "frame";
            return "call";
        }

        static bool DerivesFrom(TypeDefinition type, string baseName)
        {
            try
            {
                for (TypeReference current = type.BaseType; current != null; current = current.Resolve()?.BaseType)
                    if (current.Name == baseName) return true;
            }
            catch (Exception) { }
            return false;
        }

        static string TargetOf(IEnumerable<CustomAttribute> attributes)
        {
            foreach (CustomAttribute attribute in attributes.Where(a => a.AttributeType.Name == "HarmonyPatch"))
            {
                TypeReference type = null;
                string name = null;
                foreach (CustomAttributeArgument argument in attribute.ConstructorArguments)
                {
                    if (argument.Value is TypeReference typeReference) type = typeReference;
                    else if (argument.Value is string text && name == null) name = text;
                }
                if (type != null || name != null) return (type != null ? type.Name : "?") + "." + (name ?? "?");
            }
            return null;
        }

        public static List<HookEntry> Find(ModuleDefinition module)
        {
            var found = new List<HookEntry>();
            foreach (TypeDefinition type in module.GetTypes())
            {
                string classTarget = TargetOf(type.CustomAttributes);
                bool behaviour = DerivesFrom(type, "MonoBehaviour");
                bool coroutine = type.Name.Contains(">d__");
                foreach (MethodDefinition method in type.Methods.Where(m => m.HasBody))
                {
                    string methodTarget = TargetOf(method.CustomAttributes);
                    string target = methodTarget ?? (PatchMethodNames.Contains(method.Name) ? classTarget : null);
                    string name = type.FullName + "." + method.Name;
                    if (target != null && (PatchMethodNames.Contains(method.Name) || methodTarget != null))
                        found.Add(new HookEntry { Name = name, Kind = "patch-" + method.Name.ToLowerInvariant(), Target = target, Trigger = TriggerOf(target.Substring(target.LastIndexOf('.') + 1)), Method = method });
                    else if (behaviour && UnityMessages.Contains(method.Name))
                        found.Add(new HookEntry { Name = name, Kind = "unity", Target = type.Name + "." + method.Name, Trigger = TriggerOf(method.Name), Method = method });
                    else if (method.IsStatic && method.CustomAttributes.Any(a => a.AttributeType.Name.EndsWith("Receiver", StringComparison.Ordinal)))
                        found.Add(new HookEntry { Name = name, Kind = "receiver", Target = type.Name + "." + method.Name, Trigger = "message", Method = method });
                    else if (coroutine && method.Name == "MoveNext")
                        found.Add(new HookEntry { Name = name, Kind = "coroutine", Target = type.Name, Trigger = "coroutine step", Method = method });
                }
            }
            return found.OrderBy(h => h.Name, StringComparer.Ordinal).ToList();
        }
    }
}
