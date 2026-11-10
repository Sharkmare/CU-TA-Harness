using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CasualtiesLink
{

    public static class Reflect
    {
        private const int DefaultDepth = 1;
        private const int DefaultListLimit = 50;
        private static readonly Dictionary<string, Type> TypeCache = new Dictionary<string, Type>();
        private static readonly Dictionary<int, UnityEngine.Object> Handles = new Dictionary<int, UnityEngine.Object>();

        public static Type FindType(string name)
        {
            if (TypeCache.TryGetValue(name, out Type cached)) return cached;
            Type found = null;
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                string assemblyName = assembly.GetName().Name;
                if (assemblyName.StartsWith("System") || assemblyName.StartsWith("mscorlib") || assemblyName.StartsWith("Mono.")) continue;
                Type[] types;
                try { types = assembly.GetTypes(); } catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t != null).ToArray(); }
                foreach (var type in types)
                    if (type.Name == name || type.FullName == name) { found = type; break; }
                if (found != null) break;
            }
            if (found == null) throw new Exception("no type named '" + name + "'");
            TypeCache[name] = found;
            return found;
        }

        public static object Handle(UnityEngine.Object obj)
        {
            Handles[obj.GetInstanceID()] = obj;
            return new Dictionary<string, object> { { "$obj", obj.GetType().Name }, { "name", obj.name }, { "id", obj.GetInstanceID() } };
        }

        public static object ResolveTarget(string spec, out bool isStatic)
        {
            isStatic = false;
            switch (spec)
            {
                case "player": return RequireNotNull(PlayerCamera.main != null ? PlayerCamera.main.body : null, "no player (not in a world)");
                case "camera": return RequireNotNull(PlayerCamera.main, "no PlayerCamera (not in a world)");
                case "world": return RequireNotNull(WorldGeneration.world, "no world");
                case "console": return RequireNotNull(ConsoleScript.instance, "no console instance yet");
            }
            int colon = spec.IndexOf(':');
            if (colon < 0) throw new Exception("target must be player, camera, world, console, static:T, type:T[#n], name:N or id:N");
            string kind = spec.Substring(0, colon);
            string value = spec.Substring(colon + 1);
            if (kind == "static") { isStatic = true; return FindType(value); }
            if (kind == "id")
            {
                if (!Handles.TryGetValue(int.Parse(value), out UnityEngine.Object known) || known == null) throw new Exception("no live object with id " + value + " (handles come from find/get results)");
                return known;
            }
            if (kind == "name")
            {
                GameObject found = GameObject.Find(value);
                if (found == null) throw new Exception("no GameObject named '" + value + "'");
                return found;
            }
            if (kind == "type")
            {
                int index = 0;
                int hash = value.IndexOf('#');
                if (hash >= 0) { index = int.Parse(value.Substring(hash + 1)); value = value.Substring(0, hash); }
                var all = UnityEngine.Object.FindObjectsOfType(FindType(value));
                if (index >= all.Length) throw new Exception("only " + all.Length + " objects of type " + value);
                return all[index];
            }
            throw new Exception("unknown target kind '" + kind + "'");
        }

        private static object RequireNotNull(object value, string message)
        {
            if (value == null || (value is UnityEngine.Object o && o == null)) throw new Exception(message);
            return value;
        }

        public static object Read(string target, string path, int depth, bool nonPublic)
        {
            object root = ResolveTarget(target, out bool isStatic);
            object value = Walk(root, isStatic, PathParser.Parse(path), out _, out _, nonPublic);
            return Serialize(value, depth);
        }

        public static object Write(string target, string path, JToken newValue, bool nonPublic)
        {
            object root = ResolveTarget(target, out bool isStatic);
            var tokens = PathParser.Parse(path);
            if (tokens.Count == 0) throw new Exception("path is required for a write");
            var parentTokens = tokens.Take(tokens.Count - 1).ToList();
            object parent = Walk(root, isStatic, parentTokens, out _, out _, nonPublic);
            bool parentIsStatic = isStatic && parentTokens.Count == 0;
            PathToken last = tokens[tokens.Count - 1];
            object current = parent;
            MemberInfo member = null;
            if (last.Name != "")
            {
                member = FindMember(parentIsStatic ? (Type)parent : parent.GetType(), last.Name, nonPublic);
                if (last.Index == null)
                {
                    object converted = Convert(newValue, MemberType(member));
                    object instance = parentIsStatic ? null : parent;
                    if (member is FieldInfo f) f.SetValue(instance, converted);
                    else ((PropertyInfo)member).SetValue(instance, converted, null);
                    return Serialize(converted, 0);
                }
                current = GetMember(member, parentIsStatic ? null : parent);
            }
            SetIndexed(current, last.Index, newValue);
            return Serialize(newValue.ToString(), 0);
        }

        private static void SetIndexed(object container, object index, JToken newValue)
        {
            if (container is IDictionary dictionary)
            {
                Type valueType = container.GetType().IsGenericType ? container.GetType().GetGenericArguments()[1] : typeof(object);
                dictionary[index is long ? (object)(int)(long)index : index] = Convert(newValue, valueType);
                return;
            }
            if (container is IList list)
            {
                Type elementType = container.GetType().IsArray ? container.GetType().GetElementType() : (container.GetType().IsGenericType ? container.GetType().GetGenericArguments()[0] : typeof(object));
                list[(int)(long)index] = Convert(newValue, elementType);
                return;
            }
            throw new Exception("cannot index into " + container.GetType().Name);
        }

        private static object Walk(object start, bool startIsStatic, List<PathToken> tokens, out MemberInfo lastMember, out object lastOwner, bool nonPublic)
        {
            object current = start;
            bool currentIsStatic = startIsStatic;
            lastMember = null; lastOwner = null;
            foreach (var token in tokens)
            {
                if (current == null) throw new Exception("null reached before '" + token.Name + "'");
                if (token.Name != "")
                {
                    if (current is GameObject gameObject && FindMemberOrNull(typeof(GameObject), token.Name, nonPublic) == null)
                    {
                        Component component = gameObject.GetComponent(FindType(token.Name));
                        if (component == null) throw new Exception("GameObject '" + gameObject.name + "' has no component " + token.Name);
                        current = component;
                        currentIsStatic = false;
                    }
                    else
                    {
                        Type type = currentIsStatic ? (Type)current : current.GetType();
                        MemberInfo member = FindMember(type, token.Name, nonPublic);
                        current = GetMember(member, currentIsStatic ? null : current);
                        lastMember = member; lastOwner = current;
                        currentIsStatic = false;
                    }
                }
                if (token.Index != null) current = Index(current, token.Index);
            }
            return current;
        }

        private static object Index(object container, object index)
        {
            if (container is IDictionary dictionary)
            {
                foreach (DictionaryEntry entry in dictionary)
                    if (entry.Key.ToString() == index.ToString()) return entry.Value;
                throw new Exception("no key '" + index + "'");
            }
            if (container is IList list)
            {
                int i = (int)(long)index;
                if (i < 0 || i >= list.Count) throw new Exception("index " + i + " out of range (count " + list.Count + ")");
                return list[i];
            }
            throw new Exception("cannot index into " + container.GetType().Name);
        }

        private static MemberInfo FindMemberOrNull(Type type, string name, bool nonPublic)
        {
            var flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.FlattenHierarchy;
            if (nonPublic) flags |= BindingFlags.NonPublic;
            for (Type t = type; t != null; t = t.BaseType)
            {
                var local = flags | BindingFlags.DeclaredOnly;
                MemberInfo field = t.GetField(name, local);
                if (field != null) return field;
                MemberInfo property = t.GetProperty(name, local);
                if (property != null) return property;
            }
            return null;
        }

        private static MemberInfo FindMember(Type type, string name, bool nonPublic)
        {
            MemberInfo found = FindMemberOrNull(type, name, nonPublic);
            if (found == null) throw new Exception("type " + type.Name + " has no " + (nonPublic ? "" : "public ") + "field or property '" + name + "'");
            return found;
        }

        private static object GetMember(MemberInfo member, object instance)
        {
            if (member is FieldInfo f) return f.GetValue(instance);
            return ((PropertyInfo)member).GetValue(instance, null);
        }

        private static Type MemberType(MemberInfo member)
        {
            return member is FieldInfo f ? f.FieldType : ((PropertyInfo)member).PropertyType;
        }

        public static object Convert(JToken token, Type type)
        {
            if (type == typeof(Vector2)) return new Vector2(Num(token, "x", 0), Num(token, "y", 1));
            if (type == typeof(Vector3)) return new Vector3(Num(token, "x", 0), Num(token, "y", 1), Num(token, "z", 2));
            if (type == typeof(Color)) return new Color(Num(token, "r", 0), Num(token, "g", 1), Num(token, "b", 2), token.Type == JTokenType.Array && token.Count() < 4 ? 1f : (token["a"] != null || token.Type == JTokenType.Array ? Num(token, "a", 3) : 1f));
            if (type.IsEnum) return token.Type == JTokenType.String ? Enum.Parse(type, (string)token, true) : Enum.ToObject(type, (int)token);
            if (typeof(UnityEngine.Object).IsAssignableFrom(type))
            {
                string text = (string)token;
                if (text == null || text == "null") return null;
                return ResolveTarget(text, out _);
            }
            if (type == typeof(object)) return token.Type == JTokenType.Integer ? (object)(int)token : token.ToObject<object>();
            return token.ToObject(type);
        }

        private static float Num(JToken token, string name, int position)
        {
            JToken part = token.Type == JTokenType.Array ? token[position] : token[name];
            if (part == null) throw new Exception("missing component '" + name + "'");
            return (float)part;
        }

        public static object Serialize(object value, int depth, int listLimit = DefaultListLimit)
        {
            if (value == null) return null;
            if (value is UnityEngine.Object unityObject)
            {
                if (unityObject == null) return null;
                return Handle(unityObject);
            }
            Type type = value.GetType();
            if (type.IsPrimitive || value is string || value is decimal) return value;
            if (type.IsEnum) return value.ToString();
            if (value is Vector2 v2) return new Dictionary<string, object> { { "x", v2.x }, { "y", v2.y } };
            if (value is Vector3 v3) return new Dictionary<string, object> { { "x", v3.x }, { "y", v3.y }, { "z", v3.z } };
            if (value is Color c) return new Dictionary<string, object> { { "r", c.r }, { "g", c.g }, { "b", c.b }, { "a", c.a } };
            if (value is Quaternion q) return new Dictionary<string, object> { { "x", q.x }, { "y", q.y }, { "z", q.z }, { "w", q.w } };
            if (value is IDictionary dictionary)
            {
                var map = new Dictionary<string, object>();
                foreach (DictionaryEntry entry in dictionary) map[entry.Key.ToString()] = depth > 0 ? Serialize(entry.Value, depth - 1, listLimit) : Summary(entry.Value);
                return map;
            }
            if (value is IEnumerable enumerable)
            {
                var items = new List<object>();
                int total = 0;
                foreach (object item in enumerable)
                {
                    total++;
                    if (items.Count < listLimit) items.Add(depth > 0 ? Serialize(item, depth - 1, listLimit) : Summary(item));
                }
                return new Dictionary<string, object> { { "$count", total }, { "items", items } };
            }
            if (depth <= 0) return Summary(value);
            return DumpFields(value, depth - 1);
        }

        private static object Summary(object value)
        {
            if (value == null) return null;
            if (value is UnityEngine.Object || value is string || value.GetType().IsPrimitive || value.GetType().IsEnum || value is Vector2 || value is Vector3) return Serialize(value, 0);
            return new Dictionary<string, object> { { "$type", value.GetType().Name } };
        }

        public static Dictionary<string, object> DumpFields(object value, int depth)
        {
            var map = new Dictionary<string, object> { { "$type", value.GetType().Name } };
            foreach (var field in value.GetType().GetFields(BindingFlags.Public | BindingFlags.Instance))
            {
                try { map[field.Name] = Serialize(field.GetValue(value), depth); } catch (Exception ex) { map[field.Name] = "<" + ex.Message + ">"; }
            }
            return map;
        }

        public static Dictionary<string, object> PlainFields(object value)
        {
            var map = new Dictionary<string, object>();
            foreach (var field in value.GetType().GetFields(BindingFlags.Public | BindingFlags.Instance))
            {
                Type t = field.FieldType;
                if (!(t.IsPrimitive || t == typeof(string) || t.IsEnum)) continue;
                object v = field.GetValue(value);
                map[field.Name] = v is float f && (float.IsNaN(f) || float.IsInfinity(f)) ? null : (t.IsEnum ? v.ToString() : v);
            }
            return map;
        }

        public static object DescribeType(string name)
        {
            Type type = FindType(name);
            var members = new List<object>();
            foreach (var field in type.GetFields(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static))
                members.Add(new Dictionary<string, object> { { "name", field.Name }, { "kind", "field" }, { "type", field.FieldType.Name }, { "static", field.IsStatic } });
            foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static))
                members.Add(new Dictionary<string, object> { { "name", property.Name }, { "kind", "property" }, { "type", property.PropertyType.Name }, { "writable", property.CanWrite } });
            return new Dictionary<string, object> { { "type", type.FullName }, { "base", type.BaseType != null ? type.BaseType.Name : null }, { "members", members } };
        }
    }
}
