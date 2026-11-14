using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using HarmonyLib;
using UnityEngine;

namespace HookProfiler
{
    public class Hook
    {
        public string Name;
        public HashSet<string> Kinds = new HashSet<string>();
        public HashSet<string> Targets = new HashSet<string>();
        public MethodBase Method;
        public string IlHash;
        public int IlLength;
        public int Index = -1;
    }

    /// <summary>Finds every piece of mod code that the game can call by itself: Harmony patch bodies, Unity message methods, network receivers and coroutine steps.</summary>
    public static class Targets
    {
        static readonly string[] UnityMessages = { "Update", "FixedUpdate", "LateUpdate", "OnGUI", "OnCollisionEnter2D", "OnCollisionStay2D", "OnCollisionExit2D", "OnTriggerEnter2D", "OnTriggerStay2D", "OnTriggerExit2D" };

        public static string NameOf(MethodBase method)
        {
            return (method.DeclaringType != null ? method.DeclaringType.FullName : "?") + "." + method.Name;
        }

        public static List<Hook> Find(ISet<string> assemblyNames)
        {
            var byMethod = new Dictionary<MethodBase, Hook>();
            Hook Get(MethodBase method)
            {
                if (!byMethod.TryGetValue(method, out Hook hook))
                {
                    hook = new Hook { Name = NameOf(method), Method = method };
                    byMethod[method] = hook;
                }
                return hook;
            }

            foreach (MethodBase original in Harmony.GetAllPatchedMethods().ToList())
            {
                Patches info = Harmony.GetPatchInfo(original);
                if (info == null) continue;
                void Add(IEnumerable<Patch> patches, string kind)
                {
                    foreach (Patch patch in patches)
                    {
                        MethodInfo body = patch.PatchMethod;
                        if (body == null || body.DeclaringType == null || !assemblyNames.Contains(body.DeclaringType.Assembly.GetName().Name)) continue;
                        Hook hook = Get(body);
                        hook.Kinds.Add(kind);
                        hook.Targets.Add(NameOf(original));
                    }
                }
                Add(info.Prefixes, "prefix");
                Add(info.Postfixes, "postfix");
                Add(info.Finalizers, "finalizer");
            }

            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies().Where(a => assemblyNames.Contains(a.GetName().Name)))
            {
                Type[] types;
                try { types = assembly.GetTypes(); }
                catch (ReflectionTypeLoadException partial) { types = partial.Types.Where(t => t != null).ToArray(); }
                foreach (Type type in types)
                {
                    if (type.IsGenericTypeDefinition || type.ContainsGenericParameters) continue;
                    const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
                    bool behaviour = typeof(MonoBehaviour).IsAssignableFrom(type);
                    bool coroutine = type.Name.Contains(">d__") && typeof(System.Collections.IEnumerator).IsAssignableFrom(type);
                    foreach (MethodInfo method in type.GetMethods(flags))
                    {
                        if (method.IsAbstract || method.GetMethodBody() == null) continue;
                        if (behaviour && UnityMessages.Contains(method.Name) && method.GetParameters().Length <= 1) Get(method).Kinds.Add("unity-" + method.Name);
                        else if (coroutine && method.Name == "MoveNext") Get(method).Kinds.Add("coroutine");
                        else if (method.IsStatic && method.GetCustomAttributes(false).Any(a => a.GetType().Name.EndsWith("Receiver", StringComparison.Ordinal))) Get(method).Kinds.Add("receiver");
                    }
                }
            }

            var hooks = byMethod.Values.OrderBy(h => h.Name, StringComparer.Ordinal).ThenBy(h => h.Method.MetadataToken).ToList();
            foreach (Hook hook in hooks) Describe(hook);
            return hooks;
        }

        static void Describe(Hook hook)
        {
            try
            {
                byte[] il = hook.Method.GetMethodBody()?.GetILAsByteArray() ?? new byte[0];
                hook.IlLength = il.Length;
                using (var md5 = MD5.Create()) hook.IlHash = BitConverter.ToString(md5.ComputeHash(il)).Replace("-", "").Substring(0, 12).ToLowerInvariant();
            }
            catch (Exception) { hook.IlHash = "unreadable"; }
        }
    }
}
