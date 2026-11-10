using System.Linq;

namespace CasualtiesLink.Tests
{
    public static class KeyWindowTests
    {
        private const int Key = 119;
        private const int OtherKey = 100;

        public static void Register(TestSuite suite)
        {
            suite.Add("key windows: a tap is held for exactly the frames after the command", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 3, 10);
                Check.False(windows.IsHeld(Key, 10), "not held on the command frame");
                for (int frame = 11; frame <= 13; frame++) Check.True(windows.IsHeld(Key, frame), "held on frame " + frame);
                Check.False(windows.IsHeld(Key, 14), "released after three frames");
            });

            suite.Add("key windows: the down edge is the first held frame only", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 3, 10);
                Check.False(windows.IsDown(Key, 10), "frame 10");
                Check.True(windows.IsDown(Key, 11), "frame 11");
                Check.False(windows.IsDown(Key, 12), "frame 12");
            });

            suite.Add("key windows: the up edge is the frame after the last held frame", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 3, 10);
                Check.False(windows.IsUp(Key, 13), "frame 13");
                Check.True(windows.IsUp(Key, 14), "frame 14");
                Check.False(windows.IsUp(Key, 15), "frame 15");
            });

            suite.Add("key windows: a hold lasts until it is released and has no up edge before that", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 0, 10);
                Check.True(windows.IsHeld(Key, 11), "first frame");
                Check.True(windows.IsHeld(Key, 100000), "much later");
                Check.False(windows.IsUp(Key, 100001), "no up edge while held");
            });

            suite.Add("key windows: releasing a hold ends it on the release frame and raises the up edge after", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 0, 10);
                windows.Release(Key, 20);
                Check.True(windows.IsHeld(Key, 20), "still held on the release frame");
                Check.False(windows.IsHeld(Key, 21), "released after");
                Check.True(windows.IsUp(Key, 21), "up edge");
            });

            suite.Add("key windows: releasing a tap changes nothing", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 3, 10);
                windows.Release(Key, 11);
                Check.True(windows.IsHeld(Key, 13), "still held to the end of the tap");
            });

            suite.Add("key windows: a hold released on its own command frame is a down and an up on the same frame and never held", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 0, 10);
                windows.Release(Key, 10);
                Check.False(windows.IsHeld(Key, 11), "never held");
                Check.True(windows.IsDown(Key, 11), "down edge");
                Check.True(windows.IsUp(Key, 11), "up edge");
            });

            suite.Add("key windows: release all ends every hold but leaves taps running", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 0, 10);
                windows.Press(OtherKey, 5, 10);
                windows.ReleaseAll(12);
                Check.False(windows.IsHeld(Key, 13), "hold released");
                Check.True(windows.IsHeld(OtherKey, 13), "tap continues");
            });

            suite.Add("key windows: pressing again restarts the window", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 2, 10);
                windows.Press(Key, 2, 50);
                Check.False(windows.IsHeld(Key, 11), "old window gone");
                Check.True(windows.IsHeld(Key, 51), "new window");
            });

            suite.Add("key windows: keys are independent", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 3, 10);
                Check.False(windows.IsHeld(OtherKey, 11), "other key");
                Check.Equal(1, windows.HeldKeys(11).Count, "held keys");
                Check.Equal(Key, windows.HeldKeys(11).First(), "held key");
            });

            suite.Add("key windows: finished windows are dropped after their up edge frame", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 3, 10);
                windows.EndFrame(14);
                Check.Equal(1, windows.Count, "kept for the up edge frame");
                windows.EndFrame(15);
                Check.Equal(0, windows.Count, "dropped after");
            });

            suite.Add("key windows: a hold is never dropped, even at the largest frame number", () =>
            {
                var windows = new KeyWindows();
                windows.Press(Key, 0, 10);
                windows.EndFrame(int.MaxValue);
                Check.Equal(1, windows.Count, "kept");
                Check.False(windows.IsUp(Key, int.MaxValue), "no up edge for a hold");
            });
        }
    }
}
