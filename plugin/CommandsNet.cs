using System.Collections.Generic;

namespace CasualtiesLink
{
    public static partial class Commands
    {
        private static void RegisterNet()
        {
            Add("net_counters", "Counts of Together custom messages this game sent, by direction and message hash (toHost, toPlayer, toClients). Read only; the tap is installed once Together has loaded.", args =>
                new Dictionary<string, object>
                {
                    { "installed", NetTap.Installed }, { "status", NetTap.Status },
                    { "total", NetTap.Counter.Total }, { "counts", NetTap.Counter.Snapshot() },
                });

            Add("net_reset", "Sets the custom message counters to zero.", args =>
            {
                NetTap.Counter.Reset();
                return new Dictionary<string, object> { { "total", NetTap.Counter.Total } };
            });

            Add("message_hash", "The hash Together puts on the wire for a custom message name, as hex, so counters can be matched to names. Uses Together's own CreateNamedWriter.", args =>
                new Dictionary<string, object> { { "name", Str(args, "name", null, true) }, { "hash", NetTap.HashOfName(Str(args, "name", null, true)) } },
                false, Arg("name", "string", "Message name including the plugin prefix, e.g. CasualtiesSize.Hello", true));
        }
    }
}
