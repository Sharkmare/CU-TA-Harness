using System;
using System.Linq;
using System.Reflection;
using HarmonyLib;

namespace CasualtiesLink
{
    public static class NetTap
    {
        private const string TogetherNetTypeName = "Together.Net, CasualtiesMP";
        private const string MultiplayerTypeName = "Together.Multiplayer, CasualtiesMP";
        private const string PeerTypeName = "LiteNetLib.LiteNetPeer";
        private const string AnySendMethodName = "Client_Send";
        private const string ChokepointName = "SendInternal";
        private const string DirectionToHost = "toHost";
        private const string DirectionToPlayer = "toPlayer";
        private const int HashedPrefixLength = 5;

        public static readonly MessageCounter Counter = new MessageCounter();
        public static bool Installed { get; private set; }
        public static string Status { get; private set; } = "not tried";

        private static PropertyInfo isServerProperty;

        public static void TryInstall()
        {
            if (Installed) return;
            Type together = Type.GetType(TogetherNetTypeName);
            if (together == null)
            {
                Status = "Together not loaded";
                return;
            }
            try
            {
                MethodInfo anySend = together.GetMethods(BindingFlags.Public | BindingFlags.Static).First(method => method.Name == AnySendMethodName);
                Type peer = anySend.GetParameters()[0].ParameterType.Assembly.GetType(PeerTypeName);
                if (peer == null) throw new MissingMemberException(PeerTypeName);
                isServerProperty = together.GetProperty("IsServer", BindingFlags.Public | BindingFlags.Static);
                MethodInfo target = peer.GetMethods(BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                    .FirstOrDefault(method => method.Name == ChokepointName && method.GetParameters().Length > 0 && method.GetParameters()[0].ParameterType.Name.StartsWith("ReadOnlySpan"));
                if (target == null) throw new MissingMethodException(peer.FullName, ChokepointName);
                new Harmony(Plugin.Guid + ".net").Patch(target, prefix: new HarmonyMethod(typeof(NetTap).GetMethod(nameof(Outgoing), BindingFlags.Public | BindingFlags.Static)));
                Installed = true;
                Status = "installed on " + peer.Name + "." + ChokepointName;
            }
            catch (Exception exception)
            {
                Status = "failed: " + exception.Message;
            }
        }

        public static void Outgoing(ReadOnlySpan<byte> __0)
        {
            if (__0.Length < HashedPrefixLength || __0[0] != MessageCounter.CustomMessageId) return;
            Counter.Record(LocalIsServer() ? DirectionToPlayer : DirectionToHost, __0.Slice(0, HashedPrefixLength).ToArray(), HashedPrefixLength);
        }

        private static bool LocalIsServer()
        {
            try { return isServerProperty != null && (bool)isServerProperty.GetValue(null, null); }
            catch (Exception) { return false; }
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
