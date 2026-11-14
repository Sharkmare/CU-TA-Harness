using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Mono.Cecil;

namespace IlCost
{
    public class Options
    {
        public double HierarchyDepth = 4;
        public double SceneObjects = 5000;
        public double CollisionsPerSecond = 200;
        public double Fps = 60;
        public double TickHz = 50;
        public double MessagesPerSecond = 60;
    }

    public class Row
    {
        public string Name { get; set; }
        public string Kind { get; set; }
        public string Target { get; set; }
        public string Trigger { get; set; }
        public SortedDictionary<string, double> Fixed { get; set; } = new SortedDictionary<string, double>();
        public SortedDictionary<string, double> InLoop { get; set; } = new SortedDictionary<string, double>();
        public SortedDictionary<string, double> CheapestFixed { get; set; } = new SortedDictionary<string, double>();
        public double EstimatedNanosecondsPerTrigger { get; set; }
        public double EstimatedCheapestNanosecondsPerTrigger { get; set; }
        public double EstimatedLoopNanosecondsPerIteration { get; set; }
        public double TriggersPerSecond { get; set; }
        public double EstimatedShareOfFramePercent { get; set; }
        public double EstimatedCheapestShareOfFramePercent { get; set; }
        public List<string> CheapestSites { get; set; } = new List<string>();
    }

    public static class Profile
    {
        public static double Cost(string category, double count, Options options)
        {
            double unit = Rules.EstimatedNanoseconds[category];
            if (category == Rules.GetComponentInParent) unit *= options.HierarchyDepth;
            if (category == Rules.SceneScan) unit *= options.SceneObjects / 1000.0;
            return unit * count;
        }

        public static double TriggersPerSecond(string trigger, Options options)
        {
            switch (trigger)
            {
                case "collision": return options.CollisionsPerSecond;
                case "physics tick": return options.TickHz;
                case "frame": return options.Fps;
                case "message": return options.MessagesPerSecond;
                default: return 0;
            }
        }

        public static double TallyCost(Tally tally, Options options)
        {
            return tally.Sites.Values.Where(s => !s.InLoop).Sum(s => Cost(s.Category, s.Count, options));
        }

        public static Row Build(HookEntry hook, Result result, Options options)
        {
            Tally tally = result.Upper;
            var row = new Row { Name = Regex.Replace(hook.Name, @">d__\d+", ">d__"), Kind = hook.Kind, Target = hook.Target, Trigger = hook.Trigger };
            row.CheapestSites = result.Cheapest.Sites.Values.Where(s => s.Category != Rules.UnityNullCheck && s.Category != Rules.UnityOther).OrderBy(s => s.Where, StringComparer.Ordinal).Select(s => s.Where + " -> " + s.Callee + (s.Count > 1 ? " x" + s.Count : "") + (s.InLoop ? " [loop]" : "")).ToList();
            foreach (string category in result.Cheapest.Categories())
            {
                double cheapCount = result.Cheapest.Count(category, false);
                if (cheapCount > 0) { row.CheapestFixed[category] = cheapCount; row.EstimatedCheapestNanosecondsPerTrigger += Cost(category, cheapCount, options); }
            }
            foreach (string category in tally.Categories())
            {
                double fixedCount = tally.Count(category, false), loopCount = tally.Count(category, true);
                if (fixedCount > 0) { row.Fixed[category] = fixedCount; row.EstimatedNanosecondsPerTrigger += Cost(category, fixedCount, options); }
                if (loopCount > 0) { row.InLoop[category] = loopCount; row.EstimatedLoopNanosecondsPerIteration += Cost(category, loopCount, options); }
            }
            row.TriggersPerSecond = TriggersPerSecond(hook.Trigger, options);
            row.EstimatedShareOfFramePercent = row.TriggersPerSecond * row.EstimatedNanosecondsPerTrigger / 1e9 * 100.0;
            row.EstimatedCheapestShareOfFramePercent = row.TriggersPerSecond * row.EstimatedCheapestNanosecondsPerTrigger / 1e9 * 100.0;
            return row;
        }

        public static List<Row> Run(ModuleDefinition module, Analyzer analyzer, Options options, Regex filter)
        {
            var rows = new List<Row>();
            foreach (HookEntry hook in Hooks.Find(module))
            {
                if (filter != null && !filter.IsMatch(hook.Name) && !filter.IsMatch(hook.Target ?? "")) continue;
                rows.Add(Build(hook, analyzer.Analyze(hook.Method), options));
            }
            return rows;
        }

        static string Counts(SortedDictionary<string, double> counts)
        {
            return counts.Count == 0 ? "-" : string.Join(", ", counts.Select(c => c.Key + " x" + c.Value));
        }

        public static string Markdown(List<Row> rows, Options options)
        {
            var text = new StringBuilder();
            text.AppendLine("| hook | target | trigger | cheapest path calls | cheapest est ns (ESTIMATE) | all paths upper bound calls | upper est ns (ESTIMATE) | in loops (per iteration) | rate/s | cheapest share of one core % (ESTIMATE) |");
            text.AppendLine("|---|---|---|---|---|---|---|---|---|---|");
            foreach (Row row in rows.OrderByDescending(r => r.EstimatedCheapestShareOfFramePercent).ThenByDescending(r => r.EstimatedNanosecondsPerTrigger))
                text.AppendLine(string.Format("| {0} | {1} | {2} | {3} | {4:0} | {5} | {6:0} | {7} | {8:0} | {9:0.000} |", row.Name, row.Target, row.Trigger, Counts(row.CheapestFixed), row.EstimatedCheapestNanosecondsPerTrigger, Counts(row.Fixed), row.EstimatedNanosecondsPerTrigger, Counts(row.InLoop), row.TriggersPerSecond, row.EstimatedCheapestShareOfFramePercent));
            return text.ToString();
        }

        public static string Differences(List<Row> before, List<Row> after)
        {
            var text = new StringBuilder();
            var oldByName = before.GroupBy(r => r.Name).ToDictionary(g => g.Key, g => g.OrderByDescending(r => r.EstimatedNanosecondsPerTrigger).First());
            var newByName = after.GroupBy(r => r.Name).ToDictionary(g => g.Key, g => g.OrderByDescending(r => r.EstimatedNanosecondsPerTrigger).First());
            text.AppendLine("| hook | trigger | old cheapest est ns | new cheapest est ns | change ns | old upper est ns | new upper est ns | old cheapest calls | new cheapest calls |");
            text.AppendLine("|---|---|---|---|---|---|---|---|---|");
            foreach (string name in oldByName.Keys.Union(newByName.Keys).OrderBy(n => n, StringComparer.Ordinal))
            {
                oldByName.TryGetValue(name, out Row oldRow);
                newByName.TryGetValue(name, out Row newRow);
                double oldCost = oldRow?.EstimatedCheapestNanosecondsPerTrigger ?? 0, newCost = newRow?.EstimatedCheapestNanosecondsPerTrigger ?? 0;
                double oldUpper = oldRow?.EstimatedNanosecondsPerTrigger ?? 0, newUpper = newRow?.EstimatedNanosecondsPerTrigger ?? 0;
                bool changed = Math.Abs(newCost - oldCost) >= 0.5 || Math.Abs(newUpper - oldUpper) >= 0.5 || (oldRow != null && newRow != null && Counts(oldRow.Fixed) != Counts(newRow.Fixed));
                bool addedOrRemoved = oldRow == null || newRow == null;
                if (!changed && !(addedOrRemoved && (newUpper > 0 || oldUpper > 0))) continue;
                string state = oldRow == null ? "ADDED" : newRow == null ? "REMOVED" : "";
                text.AppendLine(string.Format("| {0} {1} | {2} | {3:0} | {4:0} | {5:+0;-0;0} | {8:0} | {9:0} | {6} | {7} |", name, state, (newRow ?? oldRow).Trigger, oldCost, newCost, newCost - oldCost, oldRow == null ? "-" : Counts(oldRow.CheapestFixed), newRow == null ? "-" : Counts(newRow.CheapestFixed), oldUpper, newUpper));
            }
            return text.ToString();
        }
    }

    public static class Program
    {
        static ModuleDefinition Load(string path, List<string> searchDirectories)
        {
            var resolver = new DefaultAssemblyResolver();
            foreach (string directory in searchDirectories) resolver.AddSearchDirectory(directory);
            resolver.AddSearchDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            return ModuleDefinition.ReadModule(path, new ReaderParameters { AssemblyResolver = resolver });
        }

        static void SplitAssumption(string text, out string key, out bool value)
        {
            int equals = text.IndexOf('=');
            if (equals < 0) throw new ArgumentException("assumption must look like Type.Member=true|false: " + text);
            key = text.Substring(0, equals);
            value = bool.Parse(text.Substring(equals + 1));
        }

        public static int Main(string[] arguments)
        {
            var options = new Options();
            var search = new List<string>();
            var analysed = new List<string> { "CasualtiesMP", "Assembly-CSharp", "CUCoreLib" };
            var assumptions = new Assumptions();
            string module = null, other = null, filter = null, markdownPath = null, jsonPath = null;
            int depth = 12;
            bool explain = false;
            for (int i = 0; i < arguments.Length; i++)
            {
                string flag = arguments[i];
                string Next() { return arguments[++i]; }
                switch (flag)
                {
                    case "--mod": module = Next(); break;
                    case "--compare-with": other = Next(); break;
                    case "--search": search.AddRange(Next().Split(';')); break;
                    case "--analyse": analysed.AddRange(Next().Split(',')); break;
                    case "--assume-field": { SplitAssumption(Next(), out string key, out bool value); assumptions.Fields[key] = value; break; }
                    case "--assume-return": { SplitAssumption(Next(), out string key, out bool value); assumptions.Returns[key] = value; break; }
                    case "--filter": filter = Next(); break;
                    case "--assume-live-objects": assumptions.ObjectsAreLive = true; break;
                    case "--explain": explain = true; break;
                    case "--assume-null-field": assumptions.NullFields.Add(Next()); break;
                    case "--depth": depth = int.Parse(Next()); break;
                    case "--hierarchy-depth": options.HierarchyDepth = double.Parse(Next()); break;
                    case "--scene-objects": options.SceneObjects = double.Parse(Next()); break;
                    case "--collisions-per-second": options.CollisionsPerSecond = double.Parse(Next()); break;
                    case "--fps": options.Fps = double.Parse(Next()); break;
                    case "--tick-hz": options.TickHz = double.Parse(Next()); break;
                    case "--md": markdownPath = Next(); break;
                    case "--json": jsonPath = Next(); break;
                    default: Console.Error.WriteLine("unknown argument " + flag); return 2;
                }
            }
            if (module == null) { Console.Error.WriteLine("usage: IlCost --mod CasualtiesMP.dll [--compare-with OLD.dll] --search <managed dir>[;dir] [--assume-field Con._DEV_TELEKINESIS=false] [--assume-return Impact.Live=false] [--filter regex] [--md out.md] [--json out.json]"); return 2; }
            Regex expression = filter == null ? null : new Regex(filter);
            List<Row> rows = Profile.Run(Load(module, search), new Analyzer(analysed, assumptions, depth, tally => Profile.TallyCost(tally, options)), options, expression);
            string text = Profile.Markdown(rows, options);
            if (other != null)
            {
                List<Row> oldRows = Profile.Run(Load(other, search), new Analyzer(analysed, assumptions, depth, tally => Profile.TallyCost(tally, options)), options, expression);
                text += Environment.NewLine + "Changes against " + other + Environment.NewLine + Profile.Differences(oldRows, rows);
            }
            Console.WriteLine(text);
            if (explain)
                foreach (Row row in rows) { Console.WriteLine(); Console.WriteLine(row.Name + " (cheapest path sites)"); foreach (string site in row.CheapestSites) Console.WriteLine("  " + site); }
            if (markdownPath != null) File.WriteAllText(markdownPath, text);
            if (jsonPath != null) File.WriteAllText(jsonPath, JsonSerializer.Serialize(rows, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
    }
}
