namespace CasualtiesLink.Tests
{
    public static class LaunchSwitchTests
    {
        public static void Register(TestSuite suite)
        {
            suite.Add("launch switch: no argument and no variable means off", () =>
                Check.Equal(0, LaunchSwitch.RequestedPort(new[] { "game.exe", "-screen-width", "1280" }, null)));

            suite.Add("launch switch: the port argument turns it on", () =>
                Check.Equal(7650, LaunchSwitch.RequestedPort(new[] { "game.exe", "--link-port", "7650" }, null)));

            suite.Add("launch switch: the environment variable turns it on", () =>
                Check.Equal(7651, LaunchSwitch.RequestedPort(new[] { "game.exe" }, "7651")));

            suite.Add("launch switch: the argument wins over the variable", () =>
                Check.Equal(7650, LaunchSwitch.RequestedPort(new[] { "--link-port", "7650" }, "7651")));

            suite.Add("launch switch: an argument without a value is ignored", () =>
                Check.Equal(0, LaunchSwitch.RequestedPort(new[] { "game.exe", "--link-port" }, null)));

            suite.Add("launch switch: ports outside 1 to 65535 and words are ignored", () =>
            {
                foreach (string bad in new[] { "0", "-5", "65536", "abc", "", "7650x" })
                    Check.Equal(0, LaunchSwitch.RequestedPort(new[] { "--link-port", bad }, null), "argument '" + bad + "'");
            });

            suite.Add("launch switch: a bad argument falls back to a good variable", () =>
                Check.Equal(7651, LaunchSwitch.RequestedPort(new[] { "--link-port", "nope" }, "7651")));

            suite.Add("launch switch: a bad variable is ignored", () =>
                Check.Equal(0, LaunchSwitch.RequestedPort(new[] { "game.exe" }, "http")));

            suite.Add("launch switch: the argument name must match exactly", () =>
                Check.Equal(0, LaunchSwitch.RequestedPort(new[] { "--link-ports", "7650", "link-port", "7650" }, null)));
        }
    }
}
