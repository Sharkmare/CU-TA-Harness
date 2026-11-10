using System;
using System.Collections.Generic;
using System.Threading;

namespace CasualtiesLink
{
    public class LinkEvent
    {
        public long seq;
        public string type;
        public float time;
        public int frame;
        public Dictionary<string, object> data;
    }

    public class EventBuffer
    {
        private readonly object gate = new object();
        private readonly List<LinkEvent> events = new List<LinkEvent>();
        private readonly int capacity;
        private readonly Func<double> seconds;
        private long nextSequence = 1;

        public EventBuffer(int capacity, Func<double> seconds)
        {
            this.capacity = capacity;
            this.seconds = seconds;
        }

        public long Emit(string type, Dictionary<string, object> data, int frame)
        {
            lock (gate)
            {
                var entry = new LinkEvent { seq = nextSequence++, type = type, time = (float)seconds(), frame = frame, data = data };
                events.Add(entry);
                if (events.Count > capacity) events.RemoveRange(0, events.Count - capacity);
                Monitor.PulseAll(gate);
                return entry.seq;
            }
        }

        public long LastSequence
        {
            get { lock (gate) return nextSequence - 1; }
        }

        public Dictionary<string, object> Read(long since, int waitMilliseconds, int limit, string type)
        {
            var deadline = DateTime.UtcNow.AddMilliseconds(waitMilliseconds);
            lock (gate)
            {
                while (true)
                {
                    var found = new List<LinkEvent>();
                    foreach (var entry in events)
                    {
                        if (entry.seq <= since) continue;
                        if (type != null && entry.type != type) continue;
                        found.Add(entry);
                        if (found.Count >= limit) break;
                    }
                    var remaining = deadline - DateTime.UtcNow;
                    if (found.Count > 0 || remaining <= TimeSpan.Zero)
                        return new Dictionary<string, object> { { "events", found }, { "last", nextSequence - 1 } };
                    Monitor.Wait(gate, remaining);
                }
            }
        }
    }
}
