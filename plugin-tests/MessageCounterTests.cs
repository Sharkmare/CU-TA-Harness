namespace CasualtiesLink.Tests
{
    public static class MessageCounterTests
    {
        private static byte[] Message(byte id, byte h1, byte h2, byte h3, byte h4, params byte[] body)
        {
            var data = new byte[5 + body.Length];
            data[0] = id;
            data[1] = h1;
            data[2] = h2;
            data[3] = h3;
            data[4] = h4;
            body.CopyTo(data, 5);
            return data;
        }

        public static void Register(TestSuite suite)
        {
            suite.Add("message counter: the hash is the four bytes after the custom message id, as hex", () =>
                Check.Equal("0a0b0c0d", MessageCounter.HashOf(Message(70, 0x0a, 0x0b, 0x0c, 0x0d), 5)));

            suite.Add("message counter: only the used length of the buffer counts", () =>
            {
                var data = Message(70, 1, 2, 3, 4, 9, 9, 9);
                Check.Equal("01020304", MessageCounter.HashOf(data, 5), "exact");
                Check.Null(MessageCounter.HashOf(data, 4), "too short for a hash");
            });

            suite.Add("message counter: other message ids and empty buffers have no hash", () =>
            {
                Check.Null(MessageCounter.HashOf(Message(69, 1, 2, 3, 4), 5), "stock message");
                Check.Null(MessageCounter.HashOf(null, 0), "null");
                Check.Null(MessageCounter.HashOf(new byte[0], 0), "empty");
            });

            suite.Add("message counter: custom messages are counted by direction and hash", () =>
            {
                var counter = new MessageCounter();
                Check.True(counter.Record("toHost", Message(70, 1, 2, 3, 4), 5), "recorded");
                counter.Record("toHost", Message(70, 1, 2, 3, 4), 5);
                counter.Record("toHost", Message(70, 9, 9, 9, 9), 5);
                counter.Record("toPlayer", Message(70, 1, 2, 3, 4), 5);
                var counts = counter.Snapshot();
                Check.Equal(2, counts["toHost:01020304"], "same message to host");
                Check.Equal(1, counts["toHost:09090909"], "other message to host");
                Check.Equal(1, counts["toPlayer:01020304"], "same message, other direction");
                Check.Equal(4, counter.Total, "total");
            });

            suite.Add("message counter: stock messages are not counted", () =>
            {
                var counter = new MessageCounter();
                Check.False(counter.Record("toHost", Message(12, 1, 2, 3, 4), 5), "stock message recorded");
                Check.Equal(0, counter.Total, "total");
                Check.Equal(0, counter.Snapshot().Count, "keys");
            });

            suite.Add("message counter: reset clears everything and the snapshot is a copy", () =>
            {
                var counter = new MessageCounter();
                counter.Record("toHost", Message(70, 1, 2, 3, 4), 5);
                var snapshot = counter.Snapshot();
                counter.Reset();
                Check.Equal(0, counter.Total, "total");
                Check.Equal(0, counter.Snapshot().Count, "keys");
                Check.Equal(1, snapshot.Count, "earlier snapshot unchanged");
            });
        }
    }
}
