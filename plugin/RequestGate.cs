namespace CasualtiesLink
{
    public class Refusal
    {
        public int Status;
        public string Message;

        public Refusal(int status, string message)
        {
            Status = status;
            Message = message;
        }
    }

    public static class RequestGate
    {
        public const string RequiredHeader = "X-CasualtiesLink";
        public const string CommandPrefix = "/cmd/";

        public static string NormalisePath(string absolutePath)
        {
            return absolutePath.TrimEnd('/');
        }

        public static Refusal Check(string method, string absolutePath, string host, string origin, bool hasRequiredHeader, int port)
        {
            if (host != "127.0.0.1:" + port && host != "localhost:" + port) return new Refusal(403, "host header refused");
            if (origin != null) return new Refusal(403, "browser requests refused");
            string path = NormalisePath(absolutePath);
            if (method == "GET")
            {
                if (path == "" || path == "/describe" || path == "/events") return null;
                return new Refusal(404, "unknown GET path; use /describe, /events or POST /cmd/<name>");
            }
            if (method != "POST") return new Refusal(405, "method not allowed");
            if (!hasRequiredHeader) return new Refusal(403, "missing " + RequiredHeader + " header");
            if (!path.StartsWith(CommandPrefix)) return new Refusal(404, "POST to /cmd/<name>");
            return null;
        }
    }
}
