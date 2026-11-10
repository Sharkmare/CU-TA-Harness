using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace CasualtiesLink
{
    public static class NetTap
    {
        private const string NetTypeName = "Together.Net, CasualtiesMP";
        private const string MultiplayerTypeName = "Together.Multiplayer, CasualtiesMP";
        private const string WriterTypeName = "NetDataWriter";
        private const string DirectionToHost = "toHost";
        private const string DirectionToPlayer = "toPlayer";
        private const string DirectionToClients = "toClients";

        public static readonly MessageCounter Counter = new MessageCounter();
        public static bool Installed { get; private set; }
        public static string Status { get; private set; } = "not tried";

        private static PropertyInfo dataProperty;
        private static PropertyInfo lengthProperty;

        public static void TryInstall()
        {
            if (Installed) return;
            Type net = Type.GetType(NetTypeName);
            if (net == null)
            {
                Status = "Together not loaded";
                return;
            }
            try
            {
                var harmony = new Harmony(Plugin.Guid + ".net");
                PatchSend(harmony, net, "Client_Send", nameof(ToHost));
                PatchSend(harmony, net, "Server_SendTo", nameof(ToPlayer));
                PatchSend(harmony, net, "Server_SendToClients", nameof(ToClients));
                Installed = true;
                Status = "installed";
            }
            catch (Exception exception)
            {
                Status = "failed: " + exception.Message;
            }
        }

        private static void PatchSend(Harmony harmony, Type net, string method, string prefix)
        {
            MethodInfo target = net.GetMethod(method, BindingFlags.Public | BindingFlags.Static);
            if (target == null) throw new MissingMethodException(net.FullName, method);
            harmony.Patch(target, prefix: new HarmonyMethod(typeof(NetTap).GetMethod(prefix, BindingFlags.Public | BindingFlags.Static)));
        }

        public static void ToHost(object[] __args) { Record(DirectionToHost, __args); }

        public static void ToPlayer(object[] __args) { Record(DirectionToPlayer, __args); }

        public static void ToClients(object[] __args) { Record(DirectionToClients, __args); }

        private static void Record(string direction, object[] arguments)
        {
            try
            {
                foreach (object argument in arguments)
                {
                    if (argument == null || argument.GetType().Name != WriterTypeName) continue;
                    if (dataProperty == null)
                    {
                        dataProperty = argument.GetType().GetProperty("Data");
                        lengthProperty = argument.GetType().GetProperty("Length");
                    }
                    Counter.Record(direction, (byte[])dataProperty.GetValue(argument, null), (int)lengthProperty.GetValue(argument, null));
                    return;
                }
            }
            catch (Exception)
            {
            }
        }

        public static string HashOfName(string name)
        {
            Type multiplayer = Type.GetType(MultiplayerTypeName);
            if (multiplayer == null) throw new Exception("Together is not loaded");
            MethodInfo create = multiplayer.GetMethod("CreateNamedWriter", BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(string) }, null);
            if (create == null) throw new Exception("Multiplayer.CreateNamedWriter not found");
            object writer = create.Invoke(null, new object[] { name });
            PropertyInfo data = writer.GetType().GetProperty("Data");
            PropertyInfo length = writer.GetType().GetProperty("Length");
            return MessageCounter.HashOf((byte[])data.GetValue(writer, null), (int)length.GetValue(writer, null));
        }
    }
}
