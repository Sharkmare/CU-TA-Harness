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
        public const int DefaultPort = 7650;
        public const string DisabledLogLine = "CasualtiesLink DISABLED (no --link-port argument or CASUALTIES_LINK_PORT variable); inert";
        public const string EnabledLogLinePrefix = "CasualtiesLink ENABLED on port ";

        public static Plugin Instance;
        public static int BoundPort;

        private LinkServer server;

        private void Awake()
        {
            Instance = this;
            int port = LaunchSwitch.RequestedPort(System.Environment.GetCommandLineArgs(), System.Environment.GetEnvironmentVariable(LaunchSwitch.PortEnvironmentVariable));
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
