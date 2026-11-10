using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;

namespace CasualtiesLink.Tests
{
    public static class EventBufferTests
    {
        private static EventBuffer NewBuffer(int capacity = 100)
        {
            return new EventBuffer(capacity, () => 1.5);
        }

        private static List<LinkEvent> EventsOf(Dictionary<string, object> reply)
        {
            return (List<LinkEvent>)reply["events"];
        }

        private static Dictionary<string, object> Data()
        {
            return new Dictionary<string, object>();
        }

        public static void Register(TestSuite suite)
        {
            suite.Add("event buffer: sequence numbers start at 1 and rise by one", () =>
            {
                var buffer = NewBuffer();
                Check.Equal(0L, buffer.LastSequence, "empty");
                Check.Equal(1L, buffer.Emit("a", Data(), 0), "first");
                Check.Equal(2L, buffer.Emit("b", Data(), 0), "second");
                Check.Equal(2L, buffer.LastSequence, "last");
            });

            suite.Add("event buffer: events carry type, frame, time and data", () =>
            {
                var buffer = NewBuffer();
                buffer.Emit("damage", new Dictionary<string, object> { { "limb", "Head" } }, 42);
                var entry = EventsOf(buffer.Read(0, 0, 10, null)).Single();
                Check.Equal("damage", entry.type, "type");
                Check.Equal(42, entry.frame, "frame");
                Check.Equal(1.5f, entry.time, "time");
                Check.Equal((object)"Head", entry.data["limb"], "data");
            });

            suite.Add("event buffer: reading since a sequence returns only newer events", () =>
            {
                var buffer = NewBuffer();
                for (int i = 0; i < 5; i++) buffer.Emit("a", Data(), 0);
                var reply = buffer.Read(3, 0, 10, null);
                Check.Equal(2, EventsOf(reply).Count, "count");
                Check.Equal(4L, EventsOf(reply)[0].seq, "first returned");
                Check.Equal((object)5L, reply["last"], "last");
            });

            suite.Add("event buffer: the type filter keeps only that type", () =>
            {
                var buffer = NewBuffer();
                buffer.Emit("damage", Data(), 0);
                buffer.Emit("death", Data(), 0);
                buffer.Emit("damage", Data(), 0);
                Check.Equal(2, EventsOf(buffer.Read(0, 0, 10, "damage")).Count, "damage");
                Check.Equal(1, EventsOf(buffer.Read(0, 0, 10, "death")).Count, "death");
                Check.Equal(0, EventsOf(buffer.Read(0, 0, 10, "none")).Count, "none");
            });

            suite.Add("event buffer: the limit caps the number returned and keeps the oldest", () =>
            {
                var buffer = NewBuffer();
                for (int i = 0; i < 10; i++) buffer.Emit("a", Data(), 0);
                var events = EventsOf(buffer.Read(0, 0, 3, null));
                Check.Equal(3, events.Count, "count");
                Check.Equal(1L, events[0].seq, "oldest first");
            });

            suite.Add("event buffer: the oldest events are dropped beyond the capacity", () =>
            {
                var buffer = NewBuffer(3);
                for (int i = 0; i < 7; i++) buffer.Emit("a", Data(), 0);
                var events = EventsOf(buffer.Read(0, 0, 100, null));
                Check.Equal(3, events.Count, "kept");
                Check.Equal(5L, events[0].seq, "oldest kept");
                Check.Equal(7L, buffer.LastSequence, "numbering continues");
            });

            suite.Add("event buffer: an empty read without waiting returns at once with the last sequence", () =>
            {
                var buffer = NewBuffer();
                buffer.Emit("a", Data(), 0);
                var watch = Stopwatch.StartNew();
                var reply = buffer.Read(1, 0, 10, null);
                Check.Equal(0, EventsOf(reply).Count, "no events");
                Check.Equal((object)1L, reply["last"], "last");
                Check.True(watch.ElapsedMilliseconds < 500, "returned at once");
            });

            suite.Add("event buffer: a waiting read times out with nothing when no event comes", () =>
            {
                var buffer = NewBuffer();
                var watch = Stopwatch.StartNew();
                var reply = buffer.Read(0, 150, 10, null);
                Check.Equal(0, EventsOf(reply).Count, "no events");
                Check.True(watch.ElapsedMilliseconds >= 100, "waited");
                Check.True(watch.ElapsedMilliseconds < 3000, "gave up");
            });

            suite.Add("event buffer: a waiting read wakes as soon as another thread emits", () =>
            {
                var buffer = NewBuffer();
                var emitter = new Thread(() => { Thread.Sleep(100); buffer.Emit("late", Data(), 0); });
                emitter.Start();
                var watch = Stopwatch.StartNew();
                var reply = buffer.Read(0, 10000, 10, null);
                emitter.Join();
                Check.Equal("late", EventsOf(reply).Single().type, "event");
                Check.True(watch.ElapsedMilliseconds < 5000, "woke early");
            });

            suite.Add("event buffer: a waiting read ignores events of another type and keeps waiting", () =>
            {
                var buffer = NewBuffer();
                var emitter = new Thread(() => { Thread.Sleep(50); buffer.Emit("other", Data(), 0); Thread.Sleep(100); buffer.Emit("wanted", Data(), 0); });
                emitter.Start();
                var reply = buffer.Read(0, 10000, 10, "wanted");
                emitter.Join();
                Check.Equal("wanted", EventsOf(reply).Single().type, "event");
            });

            suite.Add("event buffer: events emitted from many threads all get distinct sequence numbers", () =>
            {
                var buffer = NewBuffer(10000);
                var threads = Enumerable.Range(0, 4).Select(_ => new Thread(() => { for (int i = 0; i < 250; i++) buffer.Emit("a", Data(), 0); })).ToList();
                threads.ForEach(t => t.Start());
                threads.ForEach(t => t.Join());
                var sequences = EventsOf(buffer.Read(0, 0, 10000, null)).Select(e => e.seq).ToList();
                Check.Equal(1000, sequences.Count, "count");
                Check.Equal(1000, sequences.Distinct().Count(), "distinct");
                Check.True(sequences.SequenceEqual(sequences.OrderBy(s => s)), "in order");
            });
        }
    }
}
