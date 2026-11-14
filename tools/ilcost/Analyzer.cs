using System;
using System.Collections.Generic;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

namespace IlCost
{
    /// <summary>Facts the analysis may assume about the world, so a dev feature that is off prunes its own branches. Keys are "Type.Member".</summary>
    public class Assumptions
    {
        public Dictionary<string, bool> Fields = new Dictionary<string, bool>();
        public Dictionary<string, bool> Returns = new Dictionary<string, bool>();
        /// <summary>When true, a null test on a reference or on a Unity object is taken to find a live non-null object, so the happy path is followed instead of the null early out.</summary>
        public bool ObjectsAreLive;
        /// <summary>Static reference fields that hold null in the state being analysed ("Type.field").</summary>
        public HashSet<string> NullFields = new HashSet<string>();
    }

    public class Site
    {
        public string Category;
        public string Callee;
        public string Where;
        public double Count;
        public bool InLoop;
    }

    /// <summary>The costed call sites reachable from one method, with the loop flag carried through callees.</summary>
    public class Tally
    {
        public Dictionary<string, Site> Sites = new Dictionary<string, Site>();

        public void Add(string category, string callee, string where, double count, bool inLoop)
        {
            string key = where + "|" + callee + "|" + inLoop;
            if (Sites.TryGetValue(key, out Site existing)) { existing.Count += count; return; }
            Sites[key] = new Site { Category = category, Callee = callee, Where = where, Count = count, InLoop = inLoop };
        }

        public void Merge(Tally other, bool callSiteInLoop)
        {
            foreach (Site site in other.Sites.Values) Add(site.Category, site.Callee, site.Where, site.Count, site.InLoop || callSiteInLoop);
        }

        public double Count(string category, bool inLoop)
        {
            return Sites.Values.Where(s => s.Category == category && s.InLoop == inLoop).Sum(s => s.Count);
        }

        public IEnumerable<string> Categories()
        {
            return Sites.Values.Select(s => s.Category).Distinct().OrderBy(c => c, StringComparer.Ordinal);
        }
    }

    /// <summary>Upper is every costed site on any live path (loops counted once, listed apart). Cheapest is the sites along the lowest cost path from entry to a return, the route a hook takes when its early outs fire. The real per call cost lies between the two.</summary>
    public class Result
    {
        public Tally Upper = new Tally();
        public Tally Cheapest = new Tally();
    }

    /// <summary>Walks the compiled IL of a method and of everything it calls inside the analysed assemblies. Branches on assumed static flags or assumed return values are resolved. Loops are found from backward branches.</summary>
    public class Analyzer
    {
        readonly HashSet<string> analysedAssemblies;
        readonly Assumptions assumptions;
        readonly int maximumDepth;
        readonly Func<Tally, double> cost;
        readonly Dictionary<string, Result> memo = new Dictionary<string, Result>();
        readonly HashSet<MethodDefinition> active = new HashSet<MethodDefinition>();

        public Analyzer(IEnumerable<string> analysedAssemblyNames, Assumptions assumptions, int maximumDepth, Func<Tally, double> cost)
        {
            analysedAssemblies = new HashSet<string>(analysedAssemblyNames);
            this.assumptions = assumptions;
            this.maximumDepth = maximumDepth;
            this.cost = cost;
        }

        public static string KeyOf(MethodReference method) { return method.DeclaringType.Name + "." + method.Name; }

        /// <summary>nullArguments has bit k set when the call site passes a literal null as parameter k, so the callee is analysed knowing that.</summary>
        public Result Analyze(MethodDefinition method, int depth = 0, int nullArguments = 0)
        {
            string key = method.FullName + "#" + nullArguments;
            if (memo.TryGetValue(key, out Result known)) return known;
            var result = new Result();
            if (!method.HasBody || depth > maximumDepth || !active.Add(method)) return result;
            try
            {
                Walk(method, depth, result, nullArguments);
            }
            finally
            {
                active.Remove(method);
            }
            memo[key] = result;
            return result;
        }

        static bool IsSimpleLoad(Instruction instruction)
        {
            string name = instruction.OpCode.Name;
            return name.StartsWith("ldarg", StringComparison.Ordinal) || name.StartsWith("ldloc", StringComparison.Ordinal) || name.StartsWith("ldc", StringComparison.Ordinal) || name == "ldnull" || name == "ldstr" || name == "ldsfld";
        }

        int NullArgumentMask(MethodDefinition caller, int callerNulls, Instruction[] code, int callIndex, MethodReference callee)
        {
            int count = callee.Parameters.Count;
            if (count == 0 || callIndex < count) return 0;
            int mask = 0;
            for (int i = 0; i < count; i++)
            {
                Instruction load = code[callIndex - count + i];
                if (!IsSimpleLoad(load)) return 0;
                if (load.OpCode.Code == Code.Ldnull) mask |= 1 << i;
                else
                {
                    int forwarded = ArgumentIndex(caller, load);
                    if (forwarded >= 0 && forwarded < 31 && (callerNulls & (1 << forwarded)) != 0) mask |= 1 << i;
                }
            }
            return mask;
        }

        static int ArgumentIndex(MethodDefinition method, Instruction load)
        {
            int raw;
            switch (load.OpCode.Code)
            {
                case Code.Ldarg_0: raw = 0; break;
                case Code.Ldarg_1: raw = 1; break;
                case Code.Ldarg_2: raw = 2; break;
                case Code.Ldarg_3: raw = 3; break;
                case Code.Ldarg:
                case Code.Ldarg_S:
                    return ((ParameterDefinition)load.Operand).Index;
                default: return -1;
            }
            return raw - (method.IsStatic ? 0 : 1);
        }

        static TypeReference LoadedType(MethodDefinition method, Instruction load)
        {
            switch (load.OpCode.Code)
            {
                case Code.Ldarg_0: return method.IsStatic ? ParameterAt(method, 0) : method.DeclaringType;
                case Code.Ldarg_1: return ParameterAt(method, method.IsStatic ? 1 : 0);
                case Code.Ldarg_2: return ParameterAt(method, method.IsStatic ? 2 : 1);
                case Code.Ldarg_3: return ParameterAt(method, method.IsStatic ? 3 : 2);
                case Code.Ldarg:
                case Code.Ldarg_S:
                    { var parameter = (ParameterDefinition)load.Operand; return parameter.ParameterType; }
                case Code.Ldloc_0: return LocalAt(method, 0);
                case Code.Ldloc_1: return LocalAt(method, 1);
                case Code.Ldloc_2: return LocalAt(method, 2);
                case Code.Ldloc_3: return LocalAt(method, 3);
                case Code.Ldloc:
                case Code.Ldloc_S:
                    return ((VariableDefinition)load.Operand).VariableType;
                case Code.Ldfld:
                case Code.Ldsfld:
                    return ((FieldReference)load.Operand).FieldType;
            }
            return null;
        }

        static TypeReference ParameterAt(MethodDefinition method, int position)
        {
            int index = method.IsStatic ? position : position;
            return index >= 0 && index < method.Parameters.Count ? method.Parameters[index].ParameterType : null;
        }

        static TypeReference LocalAt(MethodDefinition method, int index)
        {
            return index < method.Body.Variables.Count ? method.Body.Variables[index].VariableType : null;
        }

        /// <summary>Whether the object tested by the branch is non-null: false for an assumed null static field, true for any other reference or Unity object when ObjectsAreLive, otherwise unknown.</summary>
        bool? TestedObjectIsNonNull(MethodDefinition method, Instruction source, int nullArguments)
        {
            int argument = ArgumentIndex(method, source);
            if (argument >= 0 && argument < 31 && (nullArguments & (1 << argument)) != 0) return false;
            if (source.OpCode.Code == Code.Ldsfld && source.Operand is FieldReference field && assumptions.NullFields.Contains(field.DeclaringType.Name + "." + field.Name)) return false;
            if (!assumptions.ObjectsAreLive) return null;
            TypeReference loaded = LoadedType(method, source);
            if (loaded == null || loaded.IsValueType || loaded.IsPrimitive) return null;
            return true;
        }

        bool? JumpTaken(MethodDefinition method, Instruction[] code, int index, int nullArguments)
        {
            Code op = code[index].OpCode.Code;
            if (index == 0 || !(op == Code.Brfalse || op == Code.Brfalse_S || op == Code.Brtrue || op == Code.Brtrue_S)) return null;
            Instruction before = code[index - 1];
            bool? value = null;
            if ((before.OpCode.Code == Code.Call || before.OpCode.Code == Code.Callvirt) && before.Operand is MethodReference test && test.DeclaringType.FullName == "UnityEngine.Object")
            {
                if (test.Name == "op_Implicit" && index >= 2) value = TestedObjectIsNonNull(method, code[index - 2], nullArguments);
                else if (index >= 3 && code[index - 2].OpCode.Code == Code.Ldnull)
                {
                    bool? nonNull = TestedObjectIsNonNull(method, code[index - 3], nullArguments);
                    if (nonNull != null) value = test.Name == "op_Inequality" ? nonNull : test.Name == "op_Equality" ? !nonNull : null;
                }
            }
            else if (before.OpCode.Code == Code.Ldsfld || before.OpCode.Code == Code.Ldarg_0 || before.OpCode.Code == Code.Ldarg_1 || before.OpCode.Code == Code.Ldarg_2 || before.OpCode.Code == Code.Ldarg_3 || before.OpCode.Code == Code.Ldarg || before.OpCode.Code == Code.Ldarg_S || before.OpCode.Code == Code.Ldloc_0 || before.OpCode.Code == Code.Ldloc_1 || before.OpCode.Code == Code.Ldloc_2 || before.OpCode.Code == Code.Ldloc_3 || before.OpCode.Code == Code.Ldloc || before.OpCode.Code == Code.Ldloc_S || before.OpCode.Code == Code.Ldfld)
            {
                value = TestedObjectIsNonNull(method, before, nullArguments);
            }
            if (before.OpCode.Code == Code.Ldsfld && before.Operand is FieldReference field)
            {
                string key = field.DeclaringType.Name + "." + field.Name;
                if (assumptions.Fields.TryGetValue(key, out bool assumed)) value = assumed;
            }
            else if ((before.OpCode.Code == Code.Call || before.OpCode.Code == Code.Callvirt) && before.Operand is MethodReference called)
            {
                if (assumptions.Returns.TryGetValue(KeyOf(called), out bool assumed)) value = assumed;
            }
            if (value == null) return null;
            bool jumpsWhenTrue = op == Code.Brtrue || op == Code.Brtrue_S;
            return jumpsWhenTrue ? value.Value : !value.Value;
        }

        List<int> Successors(MethodDefinition method, int nullArguments, Instruction[] code, Dictionary<Instruction, int> indexOf, int at)
        {
            var next = new List<int>();
            Instruction instruction = code[at];
            switch (instruction.OpCode.FlowControl)
            {
                case FlowControl.Branch:
                    next.Add(indexOf[(Instruction)instruction.Operand]);
                    break;
                case FlowControl.Cond_Branch:
                    if (instruction.Operand is Instruction[] targets)
                    {
                        foreach (Instruction target in targets) next.Add(indexOf[target]);
                        next.Add(at + 1);
                    }
                    else
                    {
                        bool? taken = JumpTaken(method, code, at, nullArguments);
                        if (taken != false) next.Add(indexOf[(Instruction)instruction.Operand]);
                        if (taken != true) next.Add(at + 1);
                    }
                    break;
                case FlowControl.Return:
                case FlowControl.Throw:
                    break;
                default:
                    next.Add(at + 1);
                    break;
            }
            return next.Where(n => n >= 0 && n < code.Length).ToList();
        }

        void Walk(MethodDefinition method, int depth, Result result, int nullArguments)
        {
            Instruction[] code = method.Body.Instructions.ToArray();
            var indexOf = new Dictionary<Instruction, int>();
            for (int i = 0; i < code.Length; i++) indexOf[code[i]] = i;
            var reachable = new bool[code.Length];
            var work = new Stack<int>();
            if (code.Length > 0) work.Push(0);
            foreach (ExceptionHandler handler in method.Body.ExceptionHandlers)
            {
                if (handler.HandlerStart != null) work.Push(indexOf[handler.HandlerStart]);
                if (handler.FilterStart != null) work.Push(indexOf[handler.FilterStart]);
            }
            while (work.Count > 0)
            {
                int at = work.Pop();
                if (reachable[at]) continue;
                reachable[at] = true;
                foreach (int next in Successors(method, nullArguments, code, indexOf, at)) work.Push(next);
            }

            var inLoop = new bool[code.Length];
            for (int i = 0; i < code.Length; i++)
            {
                if (!reachable[i]) continue;
                FlowControl flow = code[i].OpCode.FlowControl;
                if ((flow == FlowControl.Branch || flow == FlowControl.Cond_Branch) && code[i].Operand is Instruction target && indexOf[target] <= i)
                    for (int k = indexOf[target]; k <= i; k++) inLoop[k] = true;
            }

            string owner = method.DeclaringType.Name + "." + method.Name;
            var upperAt = new Tally[code.Length];
            var cheapestAt = new Tally[code.Length];
            var edgeCost = new double[code.Length];
            for (int i = 0; i < code.Length; i++)
            {
                if (!reachable[i]) continue;
                Instruction instruction = code[i];
                string where = owner + "+IL_" + instruction.Offset.ToString("x4");
                var upper = new Tally();
                var cheapest = new Tally();
                switch (instruction.OpCode.Code)
                {
                    case Code.Call:
                    case Code.Callvirt:
                    case Code.Newobj:
                        CountCall(method, nullArguments, code, i, where, inLoop[i], depth, upper, cheapest);
                        break;
                    case Code.Newarr:
                        upper.Add(Rules.Alloc, "newarr " + ((TypeReference)instruction.Operand).Name, where, 1, inLoop[i]);
                        cheapest.Add(Rules.Alloc, "newarr " + ((TypeReference)instruction.Operand).Name, where, 1, inLoop[i]);
                        break;
                    case Code.Box:
                        upper.Add(Rules.Alloc, "box " + ((TypeReference)instruction.Operand).Name, where, 1, inLoop[i]);
                        cheapest.Add(Rules.Alloc, "box " + ((TypeReference)instruction.Operand).Name, where, 1, inLoop[i]);
                        break;
                }
                upperAt[i] = upper;
                cheapestAt[i] = cheapest;
                edgeCost[i] = cost(cheapest);
                result.Upper.Merge(upper, false);
            }

            // Lowest cost path from the entry to any return: Bellman-Ford style relaxation, edge cost is paid on entering an instruction.
            var best = new double[code.Length];
            var previous = new int[code.Length];
            for (int i = 0; i < code.Length; i++) { best[i] = double.PositiveInfinity; previous[i] = -1; }
            if (code.Length == 0) return;
            best[0] = edgeCost[0];
            var queue = new Queue<int>();
            queue.Enqueue(0);
            while (queue.Count > 0)
            {
                int at = queue.Dequeue();
                foreach (int next in Successors(method, nullArguments, code, indexOf, at))
                {
                    if (!reachable[next]) continue;
                    double candidate = best[at] + edgeCost[next];
                    if (candidate < best[next] - 1e-9) { best[next] = candidate; previous[next] = at; queue.Enqueue(next); }
                }
            }
            int exit = -1;
            for (int i = 0; i < code.Length; i++)
                if (reachable[i] && code[i].OpCode.FlowControl == FlowControl.Return && !double.IsPositiveInfinity(best[i]) && (exit < 0 || best[i] < best[exit])) exit = i;
            for (int at = exit; at >= 0; at = previous[at])
                if (cheapestAt[at] != null) result.Cheapest.Merge(cheapestAt[at], false);
        }

        void CountCall(MethodDefinition caller, int callerNulls, Instruction[] code, int callIndex, string where, bool inLoop, int depth, Tally upper, Tally cheapest)
        {
            Instruction instruction = code[callIndex];
            var reference = (MethodReference)instruction.Operand;
            bool isNew = instruction.OpCode.Code == Code.Newobj;
            if (isNew && Rules.IsReferenceTypeConstructor(reference))
            {
                upper.Add(Rules.Alloc, "new " + reference.DeclaringType.Name, where, 1, inLoop);
                cheapest.Add(Rules.Alloc, "new " + reference.DeclaringType.Name, where, 1, inLoop);
            }
            MethodDefinition definition = null;
            try { definition = reference.Resolve(); } catch (Exception) { }
            bool analysed = definition != null && definition.HasBody && analysedAssemblies.Contains(definition.Module.Assembly.Name.Name) && !definition.DeclaringType.FullName.StartsWith("UnityEngine.", StringComparison.Ordinal);
            if (analysed)
            {
                Result inner = Analyze(definition, depth + 1, NullArgumentMask(caller, callerNulls, code, callIndex, reference));
                upper.Merge(inner.Upper, inLoop);
                cheapest.Merge(inner.Cheapest, inLoop);
                return;
            }
            string category = Rules.Classify(reference);
            if (category == Rules.Other) return;
            string callee = reference.DeclaringType.Name + "::" + reference.Name;
            upper.Add(category, callee, where, 1, inLoop);
            cheapest.Add(category, callee, where, 1, inLoop);
        }
    }
}
