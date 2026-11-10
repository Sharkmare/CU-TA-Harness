using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace CasualtiesLink
{
    public class ArgSpec
    {
        public string name;
        public string type;
        public bool required;
        public string doc;
        public object @default;
    }

    public class Cmd
    {
        public string name;
        public string doc;
        public List<ArgSpec> args = new List<ArgSpec>();
        [Newtonsoft.Json.JsonIgnore] public Func<JObject, object> Handler;
        [Newtonsoft.Json.JsonIgnore] public bool OffMainThread;
    }

    public static partial class Commands
    {
        private static readonly Dictionary<string, Cmd> Registry = new Dictionary<string, Cmd>();

        public static Cmd Find(string name) { return Registry.TryGetValue(name, out Cmd cmd) ? cmd : null; }

        public static object Describe()
        {
            return new Dictionary<string, object>
            {
                { "plugin", "CasualtiesLink" }, { "version", Plugin.Version }, { "protocol", Plugin.ProtocolVersion },
                { "port", Plugin.BoundPort },
                { "transport", "POST /cmd/<name> with a JSON object body and header " + LinkServer.RequiredHeader + ": 1; GET /describe; GET /events?since=N&wait=ms&type=T&limit=N" },
                { "commands", Registry.Values.OrderBy(c => c.name).ToList() },
            };
        }

        public static Cmd Add(string name, string doc, Func<JObject, object> handler, bool offMainThread = false, params ArgSpec[] args)
        {
            var cmd = new Cmd { name = name, doc = doc, Handler = handler, OffMainThread = offMainThread };
            cmd.args.AddRange(args);
            Registry[name] = cmd;
            return cmd;
        }

        public static ArgSpec Arg(string name, string type, string doc, bool required = false, object @default = null)
        {
            return new ArgSpec { name = name, type = type, doc = doc, required = required, @default = @default };
        }

        public static string Str(JObject a, string key, string fallback = null, bool required = false)
        {
            JToken token = a[key];
            if (token == null || token.Type == JTokenType.Null)
            {
                if (required) throw new Exception("argument '" + key + "' is required");
                return fallback;
            }
            return (string)token;
        }

        public static int Int(JObject a, string key, int fallback)
        {
            JToken token = a[key];
            return token == null || token.Type == JTokenType.Null ? fallback : (int)token;
        }

        public static float Float(JObject a, string key, float fallback)
        {
            JToken token = a[key];
            return token == null || token.Type == JTokenType.Null ? fallback : (float)token;
        }

        public static bool Bool(JObject a, string key, bool fallback)
        {
            JToken token = a[key];
            return token == null || token.Type == JTokenType.Null ? fallback : (bool)token;
        }

        public static void RegisterAll()
        {
            RegisterCore();
            RegisterRun();
            RegisterWorld();
            RegisterReflection();
            RegisterBodies();
            RegisterNet();
        }
    }
}
