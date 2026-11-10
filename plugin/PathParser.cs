using System.Collections.Generic;

namespace CasualtiesLink
{
    public class PathToken
    {
        public string Name;
        public object Index;
    }

    public static class PathParser
    {
        public static List<PathToken> Parse(string path)
        {
            var tokens = new List<PathToken>();
            if (string.IsNullOrEmpty(path)) return tokens;
            foreach (string part in path.Split('.'))
            {
                int bracket = part.IndexOf('[');
                var token = new PathToken { Name = bracket < 0 ? part : part.Substring(0, bracket) };
                if (bracket >= 0)
                {
                    string inside = part.Substring(bracket + 1, part.Length - bracket - 2);
                    token.Index = long.TryParse(inside, out long number) ? (object)number : inside.Trim('"', '\'');
                }
                tokens.Add(token);
            }
            return tokens;
        }
    }
}
