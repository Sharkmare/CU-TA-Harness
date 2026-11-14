using System.Runtime.CompilerServices;

// Stand-ins for the engine surface the analyzer recognises by name. They live in the namespace UnityEngine so that
// the compiled IL calls "UnityEngine.GameObject::GetComponentInParent" exactly as a real mod's IL does.
namespace UnityEngine
{
    public class Object
    {
        public static bool operator ==(Object a, Object b) { return ReferenceEquals(a, b); }
        public static bool operator !=(Object a, Object b) { return !ReferenceEquals(a, b); }
        public static implicit operator bool(Object o) { return !ReferenceEquals(o, null); }
        public override bool Equals(object other) { return ReferenceEquals(this, other); }
        public override int GetHashCode() { return 0; }
        public static T[] FindObjectsOfType<T>() where T : Object { return new T[0]; }
    }

    public class Component : Object
    {
        public GameObject gameObject;
        public T GetComponent<T>() { return default(T); }
        public T GetComponentInParent<T>() { return default(T); }
    }

    public class GameObject : Object
    {
        public T GetComponent<T>() { return default(T); }
        public T GetComponentInParent<T>() { return default(T); }
    }
}

namespace Fixtures
{
    using UnityEngine;

    public static class Flags
    {
        public static bool Enabled;
        public static Component Held;
    }

    public static class Hooks
    {
        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void Straight(GameObject go)
        {
            go.GetComponentInParent<Component>();
            go.GetComponentInParent<Component>();
            go.GetComponent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void StraightPlusOne(GameObject go)
        {
            go.GetComponentInParent<Component>();
            go.GetComponentInParent<Component>();
            go.GetComponentInParent<Component>();
            go.GetComponent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void StraightCopy(GameObject go)
        {
            go.GetComponentInParent<Component>();
            go.GetComponentInParent<Component>();
            go.GetComponent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void FlagGuarded(GameObject go)
        {
            if (!Flags.Enabled)
                return;
            go.GetComponentInParent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void Looped(GameObject[] list)
        {
            for (int i = 0; i < list.Length; i++)
                list[i].GetComponent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void Outer(GameObject go)
        {
            Inner(go);
            Inner(go);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        static void Inner(GameObject go)
        {
            go.GetComponentInParent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void Branchy(GameObject go, int mode)
        {
            if (mode == 0)
                return;
            Object.FindObjectsOfType<Component>();
            go.GetComponentInParent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void BranchyLate(GameObject go, int mode)
        {
            if (mode == 0)
            {
                Object.FindObjectsOfType<Component>();
                return;
            }
            return;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void PassesNull()
        {
            TakesObject(null);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        static void TakesObject(GameObject go)
        {
            if (go != null)
                go.GetComponentInParent<Component>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static void StaticStateNull(GameObject go)
        {
            if (Flags.Held == null)
                return;
            go.GetComponentInParent<Component>();
        }
    }
}
