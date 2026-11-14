using System;
using System.Linq;
using CasualtiesLink.Tests;
using Mono.Cecil;

namespace IlCost.Tests
{
    public static class TestMain
    {
        static readonly Options Costs = new Options();
        static ModuleDefinition module;

        static Result Analyse(string method, Assumptions assumptions = null, Func<string, string> unused = null)
        {
            var analyzer = new Analyzer(new[] { "IlCostTests" }, assumptions ?? new Assumptions(), 12, tally => Profile.TallyCost(tally, Costs));
            MethodDefinition definition = module.GetType("Fixtures.Hooks").Methods.Single(m => m.Name == method);
            return analyzer.Analyze(definition);
        }

        static Row RowOf(string method, Assumptions assumptions = null)
        {
            var hook = new HookEntry { Name = "Fixtures.Hooks." + method, Kind = "test", Target = "T." + method, Trigger = "collision" };
            return Profile.Build(hook, Analyse(method, assumptions), Costs);
        }

        public static int Main()
        {
            module = ModuleDefinition.ReadModule(typeof(Fixtures.Hooks).Assembly.Location);
            var suite = new TestSuite();

            suite.Add("ilcost: straight line calls are counted by category", () =>
            {
                Row row = RowOf("Straight");
                Check.Equal(2.0, row.Fixed[Rules.GetComponentInParent]);
                Check.Equal(1.0, row.Fixed[Rules.GetComponent]);
                Check.Equal(2.0, row.CheapestFixed[Rules.GetComponentInParent]);
            });

            suite.Add("ilcost: calls made by a helper are counted through the call", () =>
            {
                Check.Equal(2.0, RowOf("Outer").Fixed[Rules.GetComponentInParent]);
            });

            suite.Add("ilcost: calls inside a loop are listed apart from the fixed ones", () =>
            {
                Row row = RowOf("Looped");
                Check.False(row.Fixed.ContainsKey(Rules.GetComponent), "no fixed GetComponent");
                Check.Equal(1.0, row.InLoop[Rules.GetComponent]);
            });

            suite.Add("ilcost: the cheapest path skips the expensive branch the upper bound includes", () =>
            {
                Row row = RowOf("Branchy");
                Check.Equal(1.0, row.Fixed[Rules.SceneScan]);
                Check.False(row.CheapestFixed.ContainsKey(Rules.SceneScan), "the early return avoids the scene scan");
                Check.False(row.CheapestFixed.ContainsKey(Rules.GetComponentInParent), "and the walk");
            });

            suite.Add("ilcost: the cheapest path is chosen by cost, not by position in the code", () =>
            {
                Row row = RowOf("BranchyLate");
                Check.Equal(1.0, row.Fixed[Rules.SceneScan]);
                Check.False(row.CheapestFixed.ContainsKey(Rules.SceneScan), "the later, cheaper return wins");
            });

            suite.Add("ilcost: an assumed false flag removes the guarded call", () =>
            {
                Check.Equal(1.0, RowOf("FlagGuarded").Fixed[Rules.GetComponentInParent]);
                var off = new Assumptions();
                off.Fields["Flags.Enabled"] = false;
                Check.False(RowOf("FlagGuarded", off).Fixed.ContainsKey(Rules.GetComponentInParent), "flag off prunes the call");
                var on = new Assumptions();
                on.Fields["Flags.Enabled"] = true;
                Check.Equal(1.0, RowOf("FlagGuarded", on).CheapestFixed[Rules.GetComponentInParent]);
            });

            suite.Add("ilcost: a literal null argument is followed into the callee", () =>
            {
                var live = new Assumptions { ObjectsAreLive = true };
                Check.False(RowOf("PassesNull", live).Fixed.ContainsKey(Rules.GetComponentInParent), "null passed down, the guarded call is dead");
            });

            suite.Add("ilcost: an assumed null static field takes the early out", () =>
            {
                var heldNull = new Assumptions { ObjectsAreLive = true };
                heldNull.NullFields.Add("Flags.Held");
                Check.False(RowOf("StaticStateNull", heldNull).CheapestFixed.ContainsKey(Rules.GetComponentInParent), "held is null so the method returns first");
                var live = new Assumptions { ObjectsAreLive = true };
                Check.Equal(1.0, RowOf("StaticStateNull", live).CheapestFixed[Rules.GetComponentInParent]);
            });

            suite.Add("ilcost: identical inputs give identical rows", () =>
            {
                Row first = RowOf("Straight"), second = RowOf("StraightCopy");
                Check.Equal(first.EstimatedNanosecondsPerTrigger, second.EstimatedNanosecondsPerTrigger);
                Check.Equal(string.Join(",", first.Fixed.Select(p => p.Key + p.Value)), string.Join(",", second.Fixed.Select(p => p.Key + p.Value)));
                string differences = Profile.Differences(new[] { first }.ToList(), new[] { RowOf("Straight") }.ToList());
                Check.False(differences.Contains("Fixtures"), "no difference rows for two analyses of the same hook");
            });

            suite.Add("ilcost: one added call is detected as exactly its estimated cost", () =>
            {
                Row before = RowOf("Straight"), after = RowOf("StraightPlusOne");
                double expected = Rules.EstimatedNanoseconds[Rules.GetComponentInParent] * Costs.HierarchyDepth;
                Check.Equal(expected, after.EstimatedNanosecondsPerTrigger - before.EstimatedNanosecondsPerTrigger);
                Check.Equal(expected, after.EstimatedCheapestNanosecondsPerTrigger - before.EstimatedCheapestNanosecondsPerTrigger);
            });

            suite.Add("ilcost: a comparison of the two hook versions reports the changed hook", () =>
            {
                Row before = RowOf("Straight"), after = RowOf("StraightPlusOne");
                after.Name = before.Name;
                string differences = Profile.Differences(new[] { before }.ToList(), new[] { after }.ToList());
                Check.True(differences.Contains("Fixtures.Hooks.Straight"), "the changed hook is listed");
            });

            return suite.Run();
        }
    }
}
