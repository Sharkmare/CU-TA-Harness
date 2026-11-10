using System;
using System.Collections.Generic;

namespace CasualtiesLink
{
    public class KeyWindows
    {
        private class Window
        {
            public int FirstHeldFrame;
            public int LastHeldFrame;
        }

        private readonly Dictionary<int, Window> windows = new Dictionary<int, Window>();

        public void Press(int key, int frames, int currentFrame)
        {
            int first = currentFrame + 1;
            windows[key] = new Window { FirstHeldFrame = first, LastHeldFrame = frames <= 0 ? int.MaxValue : first + frames - 1 };
        }

        public void Release(int key, int currentFrame)
        {
            if (windows.TryGetValue(key, out Window window) && window.LastHeldFrame == int.MaxValue)
                window.LastHeldFrame = Math.Max(window.FirstHeldFrame - 1, currentFrame);
        }

        public void ReleaseAll(int currentFrame)
        {
            foreach (int key in new List<int>(windows.Keys)) Release(key, currentFrame);
        }

        public bool IsHeld(int key, int frame)
        {
            return windows.TryGetValue(key, out Window window) && frame >= window.FirstHeldFrame && frame <= window.LastHeldFrame;
        }

        public bool IsDown(int key, int frame)
        {
            return windows.TryGetValue(key, out Window window) && frame == window.FirstHeldFrame;
        }

        public bool IsUp(int key, int frame)
        {
            return windows.TryGetValue(key, out Window window) && window.LastHeldFrame != int.MaxValue && (long)frame == (long)window.LastHeldFrame + 1;
        }

        public List<int> HeldKeys(int frame)
        {
            var held = new List<int>();
            foreach (var pair in windows) if (IsHeld(pair.Key, frame)) held.Add(pair.Key);
            return held;
        }

        public void EndFrame(int frame)
        {
            var finished = new List<int>();
            foreach (var pair in windows) if ((long)frame > (long)pair.Value.LastHeldFrame + 1) finished.Add(pair.Key);
            foreach (int key in finished) windows.Remove(key);
        }

        public int Count
        {
            get { return windows.Count; }
        }
    }
}
