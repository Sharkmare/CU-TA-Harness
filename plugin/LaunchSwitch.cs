namespace CasualtiesLink
{
    public static class LaunchSwitch
    {
        public const string PortArgument = "--link-port";
        public const string PortEnvironmentVariable = "CASUALTIES_LINK_PORT";
        private const int LowestPort = 1;
        private const int HighestPort = 65535;

        public static int RequestedPort(string[] commandLine, string environmentValue)
        {
            for (int i = 0; i < commandLine.Length - 1; i++)
            {
                if (commandLine[i] == PortArgument && TryPort(commandLine[i + 1], out int fromArgument)) return fromArgument;
            }
            if (TryPort(environmentValue, out int fromEnvironment)) return fromEnvironment;
            return 0;
        }

        private static bool TryPort(string text, out int port)
        {
            port = 0;
            return !string.IsNullOrEmpty(text) && int.TryParse(text, out port) && port >= LowestPort && port <= HighestPort;
        }
    }
}
