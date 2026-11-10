using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;

namespace CasualtiesLink
{

    public static class InputInjector
    {
        private class KeyWindow { public int FirstHeldFrame; public int LastHeldFrame; }

        private static readonly Dictionary<KeyCode, KeyWindow> Windows = new Dictionary<KeyCode, KeyWindow>();
        public static Vector3? MousePosition;

        public static void Press(KeyCode key, int frames)
        {
            int first = Time.frameCount + 1;
            Windows[key] = new KeyWindow { FirstHeldFrame = first, LastHeldFrame = frames <= 0 ? int.MaxValue : first + frames - 1 };
        }

        public static void Release(KeyCode key)
        {
            if (Windows.TryGetValue(key, out KeyWindow window) && window.LastHeldFrame == int.MaxValue)
                window.LastHeldFrame = Mathf.Max(window.FirstHeldFrame - 1, Time.frameCount);
        }

        public static void ReleaseAll()
        {
            foreach (var key in new List<KeyCode>(Windows.Keys)) Release(key);
            MousePosition = null;
        }

        public static bool IsHeld(KeyCode key)
        {
            return Windows.TryGetValue(key, out KeyWindow w) && Time.frameCount >= w.FirstHeldFrame && Time.frameCount <= w.LastHeldFrame;
        }

        public static bool IsDown(KeyCode key)
        {
            return Windows.TryGetValue(key, out KeyWindow w) && Time.frameCount == w.FirstHeldFrame;
        }

        public static bool IsUp(KeyCode key)
        {
            return Windows.TryGetValue(key, out KeyWindow w) && w.LastHeldFrame != int.MaxValue && (long)Time.frameCount == (long)w.LastHeldFrame + 1;
        }

        public static object Describe()
        {
            var held = new List<string>();
            foreach (var pair in Windows) if (IsHeld(pair.Key)) held.Add(pair.Key.ToString());
            return new Dictionary<string, object> { { "held", held }, { "mouse", MousePosition.HasValue ? (object)new { x = MousePosition.Value.x, y = MousePosition.Value.y } : null } };
        }

        public static void EndFrame()
        {
            var finished = new List<KeyCode>();
            foreach (var pair in Windows) if ((long)Time.frameCount > (long)pair.Value.LastHeldFrame + 1) finished.Add(pair.Key);
            foreach (var key in finished) Windows.Remove(key);
        }
    }

    [HarmonyPatch(typeof(Input), nameof(Input.GetKey), new[] { typeof(KeyCode) })]
    public static class GetKeyPatch
    {
        private static bool Prefix(KeyCode key, ref bool __result)
        {
            if (!InputInjector.IsHeld(key)) return true;
            __result = true;
            return false;
        }
    }

    [HarmonyPatch(typeof(Input), nameof(Input.GetKeyDown), new[] { typeof(KeyCode) })]
    public static class GetKeyDownPatch
    {
        private static bool Prefix(KeyCode key, ref bool __result)
        {
            if (!InputInjector.IsDown(key)) return true;
            __result = true;
            return false;
        }
    }

    [HarmonyPatch(typeof(Input), nameof(Input.GetKeyUp), new[] { typeof(KeyCode) })]
    public static class GetKeyUpPatch
    {
        private static bool Prefix(KeyCode key, ref bool __result)
        {
            if (!InputInjector.IsUp(key)) return true;
            __result = true;
            return false;
        }
    }

    [HarmonyPatch(typeof(Input), nameof(Input.GetMouseButtonDown), new[] { typeof(int) })]
    public static class GetMouseButtonDownPatch
    {
        private static bool Prefix(int button, ref bool __result)
        {
            if (!InputInjector.IsDown(KeyCode.Mouse0 + button)) return true;
            __result = true;
            return false;
        }
    }

    [HarmonyPatch(typeof(Input), nameof(Input.GetMouseButton), new[] { typeof(int) })]
    public static class GetMouseButtonPatch
    {
        private static bool Prefix(int button, ref bool __result)
        {
            if (!InputInjector.IsHeld(KeyCode.Mouse0 + button)) return true;
            __result = true;
            return false;
        }
    }

    [HarmonyPatch(typeof(Input), nameof(Input.mousePosition), MethodType.Getter)]
    public static class MousePositionPatch
    {
        private static bool Prefix(ref Vector3 __result)
        {
            if (!InputInjector.MousePosition.HasValue) return true;
            __result = InputInjector.MousePosition.Value;
            return false;
        }
    }
}
