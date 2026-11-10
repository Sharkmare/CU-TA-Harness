using System;
using System.Collections.Generic;
using System.Text;

namespace CasualtiesLink
{
    public class MessageCounter
    {
        public const byte CustomMessageId = 70;
        private const int HashOffset = 1;
        private const int HashLength = 4;

        private readonly object gate = new object();
        private readonly Dictionary<string, int> counts = new Dictionary<string, int>();
        private int total;

        public static string HashOf(byte[] data, int length)
        {
            if (data == null || length < HashOffset + HashLength || data[0] != CustomMessageId) return null;
            var text = new StringBuilder();
            for (int i = HashOffset; i < HashOffset + HashLength; i++) text.Append(data[i].ToString("x2"));
            return text.ToString();
        }

        public bool Record(string direction, byte[] data, int length)
        {
            string hash = HashOf(data, length);
            if (hash == null) return false;
            string key = direction + ":" + hash;
            lock (gate)
            {
                int existing;
                counts.TryGetValue(key, out existing);
                counts[key] = existing + 1;
                total++;
            }
            return true;
        }

        public int Total
        {
            get { lock (gate) return total; }
        }

        public Dictionary<string, int> Snapshot()
        {
            lock (gate) return new Dictionary<string, int>(counts);
        }

        public void Reset()
        {
            lock (gate)
            {
                counts.Clear();
                total = 0;
            }
        }
    }
}
