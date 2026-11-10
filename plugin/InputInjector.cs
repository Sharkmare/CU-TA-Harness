using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;

namespace CasualtiesLink
{

    public static class InputInjector
    {
        private static readonly KeyWindows Windows = new KeyWindows();
        public static Vector3? MousePosition;

        public static void Press(KeyCode key, int frames)
        {
            Windows.Press((int)key, frames, Time.frameCount);
        }

        public static void Release(KeyCode key)
        {
            Windows.Release((int)key, Time.frameCount);
        }

        public static void ReleaseAll()
        {
            Windows.ReleaseAll(Time.frameCount);
            MousePosition = null;
        }

        public static bool IsHeld(KeyCode key)
        {
            return Windows.IsHeld((int)key, Time.frameCount);
        }

        public static bool IsDown(KeyCode key)
        {
            return Windows.IsDown((int)key, Time.frameCount);
        }

        public static bool IsUp(KeyCode key)
        {
            return Windows.IsUp((int)key, Time.frameCount);
        }

        public static object Describe()
        {
            var held = new List<string>();
            foreach (int key in Windows.HeldKeys(Time.frameCount)) held.Add(((KeyCode)key).ToString());
            return new Dictionary<string, object> { { "held", held }, { "mouse", MousePosition.HasValue ? (object)new { x = MousePosition.Value.x, y = MousePosition.Value.y } : null } };
        }

        public static void EndFrame()
        {
            Windows.EndFrame(Time.frameCount);
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
