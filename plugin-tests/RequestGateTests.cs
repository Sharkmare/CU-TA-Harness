namespace CasualtiesLink.Tests
{
    public static class RequestGateTests
    {
        private const int Port = 7650;
        private const string Host = "127.0.0.1:7650";

        private static Refusal Get(string path, string host = Host, string origin = null)
        {
            return RequestGate.Check("GET", path, host, origin, false, Port);
        }

        private static Refusal Post(string path, bool header = true, string host = Host, string origin = null)
        {
            return RequestGate.Check("POST", path, host, origin, header, Port);
        }

        public static void Register(TestSuite suite)
        {
            suite.Add("request gate: describe and events are readable on the loopback host", () =>
            {
                Check.Null(Get("/describe"), "describe");
                Check.Null(Get("/events"), "events");
                Check.Null(Get("/"), "root");
                Check.Null(Get(""), "empty path");
            });

            suite.Add("request gate: a trailing slash makes no difference", () =>
            {
                Check.Null(Get("/describe/"), "describe");
                Check.Null(Post("/cmd/status/"), "command");
            });

            suite.Add("request gate: localhost with the right port is accepted", () =>
                Check.Null(Get("/describe", "localhost:7650"), "localhost"));

            suite.Add("request gate: any other host is refused, which blocks DNS rebinding", () =>
            {
                Check.Refused(Get("/describe", "evil.example"), 403, "foreign name");
                Check.Refused(Get("/describe", "127.0.0.1:7651"), 403, "other port");
                Check.Refused(Get("/describe", "127.0.0.1"), 403, "no port");
                Check.Refused(Get("/describe", ""), 403, "empty host");
                Check.Refused(Post("/cmd/status", true, "evil.example:7650"), 403, "foreign name on POST");
            });

            suite.Add("request gate: a request with an Origin header is refused, which blocks web pages", () =>
            {
                Check.Refused(Get("/describe", Host, "http://evil.example"), 403, "GET");
                Check.Refused(Post("/cmd/status", true, Host, "http://evil.example"), 403, "POST");
                Check.Refused(Get("/describe", Host, ""), 403, "empty origin still counts");
            });

            suite.Add("request gate: a POST needs the custom header", () =>
            {
                Check.Refused(Post("/cmd/status", false), 403, "no header");
                Check.Null(Post("/cmd/status", true), "with header");
            });

            suite.Add("request gate: a POST only goes to a command path", () =>
            {
                Check.Refused(Post("/describe"), 404, "describe");
                Check.Refused(Post("/"), 404, "root");
                Check.Refused(Post("/cmdx/status"), 404, "prefix lookalike");
            });

            suite.Add("request gate: unknown GET paths are not found", () =>
            {
                Check.Refused(Get("/cmd/status"), 404, "command by GET");
                Check.Refused(Get("/etc/passwd"), 404, "anything else");
            });

            suite.Add("request gate: other methods are refused", () =>
            {
                foreach (string method in new[] { "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH" })
                    Check.Refused(RequestGate.Check(method, "/cmd/status", Host, null, true, Port), 405, method);
            });

            suite.Add("request gate: the host check comes before the method and path checks", () =>
                Check.Refused(RequestGate.Check("PUT", "/anything", "evil.example", null, false, Port), 403, "host first"));
        }
    }
}
