using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json;
using UnityEngine;

namespace HookProfiler
{
    /// <summary>Reads the chunk sleep state of the mod through reflection, so the same call works against any build of it. Driven through the link like Control.</summary>
    public static class SleepProbe
    {
        const BindingFlags AnyMember = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
        const string ModAssembly = "CasualtiesMP";
        const string SleepType = "Together.ChunkSleep";
        const string KeepType = "Together.SimKeep";
        const float KeepPickRadius = 3f;

        static Type FindType(string fullName)
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (assembly.GetName().Name != ModAssembly) continue;
                var type = assembly.GetType(fullName, false);
                if (type != null) return type;
            }
            throw new Exception("type not found: " + fullName);
        }

        static object ReadField(object owner, string name)
        {
            var field = owner.GetType().GetField(name, AnyMember);
            return field == null ? null : field.GetValue(owner);
        }

        static List<object> EntryList(Type sleep)
        {
            var field = sleep.GetField("Entries", AnyMember);
            if (field == null) throw new Exception("ChunkSleep.Entries not found");
            return ((IEnumerable)field.GetValue(null)).Cast<object>().ToList();
        }

        /// <summary>Every watched object: id, name, position, chunk key, asleep flag, activeSelf, the fix's settled flag (null on a build without it) and whether the chunk is hot for this machine right now. Also the sum of the fix's unsettled counters.</summary>
        public static string Dump()
        {
            var sleep = FindType(SleepType);
            var hot = sleep.GetMethod("Hot", AnyMember);
            var rows = new List<object>();
            foreach (var entry in EntryList(sleep))
            {
                var go = ReadField(entry, "Go") as GameObject;
                if (go == null) continue;
                Vector2 position = go.transform.position;
                rows.Add(new
                {
                    id = (int)ReadField(entry, "Id"),
                    name = go.name,
                    x = Math.Round(position.x, 2),
                    y = Math.Round(position.y, 2),
                    chunk = (long)ReadField(entry, "Chunk"),
                    placed = (bool)ReadField(entry, "Placed"),
                    asleep = (bool)ReadField(entry, "Asleep"),
                    active = go.activeSelf,
                    settled = ReadField(entry, "Settled"),
                    hot = hot == null ? (bool?)null : (bool)hot.Invoke(null, new object[] { position }),
                });
            }
            int? unsettled = null;
            var byChunk = sleep.GetField("ByChunk", AnyMember);
            if (byChunk != null && byChunk.FieldType.GetGenericArguments().Length == 2 && byChunk.FieldType.GetGenericArguments()[1].Name == "Slot")
            {
                int sum = 0;
                foreach (var slot in ((IDictionary)byChunk.GetValue(null)).Values) sum += (int)ReadField(slot, "Unsettled");
                unsettled = sum;
            }
            var world = WorldGeneration.world;
            return JsonConvert.SerializeObject(new
            {
                chunkSize = WorldGeneration.CHUNKSIZE,
                time = Time.unscaledTime,
                unsettledTotal = unsettled,
                entries = rows,
            });
        }

        /// <summary>A cheap count for fast polling: watched objects, awake ones, and the ones whose chunk is hot for this machine but that are switched off.</summary>
        public static string Pulse()
        {
            var sleep = FindType(SleepType);
            var hot = sleep.GetMethod("Hot", AnyMember);
            int watched = 0, awake = 0, hotOff = 0;
            foreach (var entry in EntryList(sleep))
            {
                var go = ReadField(entry, "Go") as GameObject;
                if (go == null) continue;
                watched++;
                if (go.activeSelf) { awake++; continue; }
                if (hot != null && (bool)hot.Invoke(null, new object[] { (Vector2)go.transform.position })) hotOff++;
            }
            return JsonConvert.SerializeObject(new { watched, awake, hotOff, frame = Time.frameCount, time = Time.unscaledTime });
        }

        /// <summary>Where the local player's body is, read from the body itself.</summary>
        public static string LocalPosition()
        {
            var body = PlayerCamera.main != null ? PlayerCamera.main.body : null;
            if (body == null) return JsonConvert.SerializeObject(new { error = "no local body" });
            Vector2 position = body.transform.position;
            return JsonConvert.SerializeObject(new { x = position.x, y = position.y });
        }

        /// <summary>The chunk key of a world position, the same way the mod packs it.</summary>
        public static string ChunkKeyAt(string x, string y)
        {
            var world = WorldGeneration.world;
            var chunk = world.BlockToChunkPos(world.WorldToBlockPos(new Vector2(float.Parse(x, System.Globalization.CultureInfo.InvariantCulture), float.Parse(y, System.Globalization.CultureInfo.InvariantCulture))));
            return JsonConvert.SerializeObject(new { cx = chunk.x, cy = chunk.y, key = ((long)chunk.x << 32) | (uint)chunk.y, chunkSize = WorldGeneration.CHUNKSIZE, halfWidth = world.halfWidth, halfHeight = world.halfHeight });
        }

        /// <summary>Starts the SimKeep window on the watched object (asleep or awake) nearest to (x, y), as a throw does. Returns its name and position, or an error text when nothing is within reach.</summary>
        public static string ArmKeep(string x, string y, string radius)
        {
            var sleep = FindType(SleepType);
            var target = new Vector2(float.Parse(x, System.Globalization.CultureInfo.InvariantCulture), float.Parse(y, System.Globalization.CultureInfo.InvariantCulture));
            GameObject best = null;
            float bestDistance = float.Parse(radius, System.Globalization.CultureInfo.InvariantCulture);
            foreach (var entry in EntryList(sleep))
            {
                var go = ReadField(entry, "Go") as GameObject;
                if (go == null) continue;
                float distance = Vector2.Distance(go.transform.position, target);
                if (distance < bestDistance) { best = go; bestDistance = distance; }
            }
            if (best == null) return JsonConvert.SerializeObject(new { error = "no watched object within " + radius });
            FindType(KeepType).GetMethod("Arm", AnyMember).Invoke(null, new object[] { best });
            return JsonConvert.SerializeObject(new { name = best.name, x = best.transform.position.x, y = best.transform.position.y });
        }
    }
}
