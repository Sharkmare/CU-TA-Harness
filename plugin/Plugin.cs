using BepInEx;
using HarmonyLib;
using UnityEngine;

namespace CasualtiesLink
{

    [BepInPlugin(Guid, "CasualtiesLink", Version)]
    public class Plugin : BaseUnityPlugin
    {
        public const string Guid = "casualtieslink";
        public const string Version = "1.0.0";
        public const int ProtocolVersion = 1;
        public const string PortEnvironmentVariable = "CASUALTIES_LINK_PORT";
        public const string PortArgument = "--link-port";
        public const int DefaultPort = 7650;
        public const string DisabledLogLine = "CasualtiesLink DISABLED (no --link-port argument or CASUALTIES_LINK_PORT variable); inert";
        public const string EnabledLogLinePrefix = "CasualtiesLink ENABLED on port ";

        public static Plugin Instance;
        public static int BoundPort;

        private LinkServer server;

        public static int RequestedPort(string[] commandLine, string environmentValue)
        {
            for (int i = 0; i < commandLine.Length - 1; i++)
                if (commandLine[i] == PortArgument && int.TryParse(commandLine[i + 1], out int fromArgument) && fromArgument > 0 && fromArgument < 65536)
                    return fromArgument;
            if (!string.IsNullOrEmpty(environmentValue) && int.TryParse(environmentValue, out int fromEnvironment) && fromEnvironment > 0 && fromEnvironment < 65536)
                return fromEnvironment;
            return 0;
        }

        private void Awake()
        {
            Instance = this;
            int port = RequestedPort(System.Environment.GetCommandLineArgs(), System.Environment.GetEnvironmentVariable(PortEnvironmentVariable));
            if (port == 0)
            {
                Logger.LogInfo(DisabledLogLine);
                return;
            }

            Application.runInBackground = true;
            var driver = new GameObject("CasualtiesLinkDriver");
            driver.hideFlags = HideFlags.HideAndDontSave;
            DontDestroyOnLoad(driver);
            driver.AddComponent<MainThread>();

            EventLog.Install();
            try
            {
                new Harmony(Guid).PatchAll(typeof(Plugin).Assembly);
            }
            catch (System.Exception ex)
            {
                Logger.LogError("Harmony patching failed: " + ex);
            }

            Commands.RegisterAll();
            server = new LinkServer(port);
            server.Start();
            BoundPort = port;
            Logger.LogInfo(EnabledLogLinePrefix + port + " (http://127.0.0.1:" + port + "/)");
        }

        private void OnDestroy()
        {
            if (server != null) server.Stop();
        }
    }
}
