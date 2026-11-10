namespace CasualtiesLink.Tests
{
    public static class Program
    {
        public static int Main()
        {
            var suite = new TestSuite();
            LaunchSwitchTests.Register(suite);
            KeyWindowTests.Register(suite);
            RequestGateTests.Register(suite);
            PathParserTests.Register(suite);
            EventBufferTests.Register(suite);
            return suite.Run();
        }
    }
}
