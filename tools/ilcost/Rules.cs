using System;
using System.Collections.Generic;
using Mono.Cecil;

namespace IlCost
{
    /// <summary>Sorts a called method into a cost category by its declaring type and name. The unit costs are ESTIMATES from general knowledge of the engine, not measurements.</summary>
    public static class Rules
    {
        public const string GetComponentInParent = "GetComponentInParent";
        public const string GetComponentFamily = "GetComponents*";
        public const string GetComponent = "GetComponent";
        public const string SceneScan = "SceneScan";
        public const string Physics = "Physics";
        public const string TransformWalk = "TransformWalk";
        public const string UnityNullCheck = "UnityNullCheck";
        public const string Lifecycle = "Lifecycle";
        public const string Linq = "LINQ";
        public const string Text = "String";
        public const string Log = "Log";
        public const string Reflection = "Reflection";
        public const string Alloc = "Alloc";
        public const string UnityOther = "UnityOther";
        public const string Other = "other";

        /// <summary>Nanoseconds per call. GetComponentInParent is per level of hierarchy walked; SceneScan is per 1000 scene objects. Guesses, labelled as such in every report.</summary>
        public static readonly Dictionary<string, double> EstimatedNanoseconds = new Dictionary<string, double>
        {
            { GetComponentInParent, 60 },
            { GetComponentFamily, 400 },
            { GetComponent, 60 },
            { SceneScan, 20000 },
            { Physics, 800 },
            { TransformWalk, 40 },
            { UnityNullCheck, 15 },
            { Lifecycle, 3000 },
            { Linq, 300 },
            { Text, 120 },
            { Log, 6000 },
            { Reflection, 1500 },
            { Alloc, 40 },
            { UnityOther, 25 },
            { Other, 0 },
        };

        public static string Classify(MethodReference method)
        {
            string type = method.DeclaringType.FullName;
            string name = method.Name;
            bool unity = type.StartsWith("UnityEngine.", StringComparison.Ordinal);
            if (name.StartsWith("GetComponentInParent", StringComparison.Ordinal) && unity) return GetComponentInParent;
            if (unity && (name.StartsWith("GetComponentsIn", StringComparison.Ordinal) || name == "GetComponents" || name.StartsWith("GetComponentInChildren", StringComparison.Ordinal))) return GetComponentFamily;
            if (unity && (name == "GetComponent" || name == "TryGetComponent")) return GetComponent;
            if (unity && (name.StartsWith("FindObject", StringComparison.Ordinal) || name.StartsWith("FindFirst", StringComparison.Ordinal) || name.StartsWith("FindAny", StringComparison.Ordinal) || name == "Find" || name.StartsWith("FindWithTag", StringComparison.Ordinal) || name.StartsWith("FindGameObjects", StringComparison.Ordinal) || name.StartsWith("FindObjectsByType", StringComparison.Ordinal))) return SceneScan;
            if (type == "UnityEngine.Physics2D" || type == "UnityEngine.Physics") return Physics;
            if (type == "UnityEngine.Transform" && (name == "IsChildOf" || name == "get_parent" || name == "GetChild" || name == "SetParent" || name == "get_childCount" || name == "get_root" || name == "FindChild" || name == "Find")) return TransformWalk;
            if (type == "UnityEngine.Object" && (name == "op_Equality" || name == "op_Inequality" || name == "op_Implicit")) return UnityNullCheck;
            if (unity && (name == "AddComponent" || name == "Instantiate" || name == "Destroy" || name == "DestroyImmediate")) return Lifecycle;
            if (type.StartsWith("System.Linq.", StringComparison.Ordinal)) return Linq;
            if (type == "System.String" && (name.StartsWith("Concat", StringComparison.Ordinal) || name == "Format" || name == "Join" || name == "Substring" || name == "Replace" || name == "Split" || name == "ToLower" || name == "ToUpper" || name == "op_Addition" || name == "ToLowerInvariant" || name == "ToUpperInvariant" || name == "Contains" || name == "StartsWith" || name == "EndsWith" || name == "IndexOf")) return Text;
            if (type == "System.Object" && name == "ToString") return Text;
            if (type == "UnityEngine.Debug" || type.StartsWith("BepInEx.Logging.", StringComparison.Ordinal)) return Log;
            if (type.StartsWith("HarmonyLib.", StringComparison.Ordinal) || type.StartsWith("System.Reflection.", StringComparison.Ordinal) || type == "System.Activator" || type == "System.Type" && (name.StartsWith("GetMethod", StringComparison.Ordinal) || name.StartsWith("GetField", StringComparison.Ordinal) || name.StartsWith("GetProperty", StringComparison.Ordinal) || name == "GetType")) return Reflection;
            if (unity) return UnityOther;
            return Other;
        }

        public static bool IsReferenceTypeConstructor(MethodReference constructor)
        {
            TypeDefinition resolved = null;
            try { resolved = constructor.DeclaringType.Resolve(); } catch (Exception) { }
            return resolved == null || !resolved.IsValueType;
        }
    }
}
