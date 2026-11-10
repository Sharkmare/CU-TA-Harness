using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace CasualtiesLink
{

    public class LinkServer
    {
        public const string RequiredHeader = "X-CasualtiesLink";
        private const int CommandWaitMilliseconds = 130000;
        private const int MaximumLongPollMilliseconds = 60000;

        private readonly int port;
        private HttpListener listener;
        private Thread acceptThread;
        private volatile bool running;

        public LinkServer(int port) { this.port = port; }

        public void Start()
        {
            listener = new HttpListener();
            listener.Prefixes.Add("http://127.0.0.1:" + port + "/");
            listener.Start();
            running = true;
            acceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "CasualtiesLink-accept" };
            acceptThread.Start();
        }

        public void Stop()
        {
            running = false;
            try { listener.Stop(); } catch { }
        }

        private void AcceptLoop()
        {
            while (running)
            {
                HttpListenerContext context;
                try { context = listener.GetContext(); }
                catch { if (!running) return; continue; }
                ThreadPool.QueueUserWorkItem(_ => Handle(context));
            }
        }

        private void Handle(HttpListenerContext context)
        {
            object body;
            int status = 200;
            try { body = Route(context); }
            catch (LinkException ex) { status = ex.Status; body = Failure(ex.Message, ex.GetType().Name); }
            catch (Exception ex) { status = 500; body = Failure(ex.Message, ex.GetType().Name); }
            try
            {
                string json = JsonConvert.SerializeObject(body, Formatting.None);
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                context.Response.StatusCode = status;
                context.Response.ContentType = "application/json; charset=utf-8";
                context.Response.ContentLength64 = bytes.Length;
                context.Response.OutputStream.Write(bytes, 0, bytes.Length);
            }
            catch { }
            finally { try { context.Response.Close(); } catch { } }
        }

        private static object Failure(string message, string kind)
        {
            return new Dictionary<string, object> { { "ok", false }, { "error", message }, { "kind", kind } };
        }

        private static object Success(object result)
        {
            return new Dictionary<string, object> { { "ok", true }, { "result", result } };
        }

        private object Route(HttpListenerContext context)
        {
            var request = context.Request;
            string host = request.Headers["Host"] ?? "";
            if (host != "127.0.0.1:" + port && host != "localhost:" + port)
                throw new LinkException(403, "host header refused");
            if (request.Headers["Origin"] != null)
                throw new LinkException(403, "browser requests refused");

            string path = request.Url.AbsolutePath.TrimEnd('/');
            if (request.HttpMethod == "GET")
            {
                if (path == "" || path == "/describe") return Success(Commands.Describe());
                if (path == "/events") return Success(ReadEvents(request.QueryString));
                throw new LinkException(404, "unknown GET path; use /describe, /events or POST /cmd/<name>");
            }
            if (request.HttpMethod != "POST") throw new LinkException(405, "method not allowed");
            if (request.Headers[RequiredHeader] == null) throw new LinkException(403, "missing " + RequiredHeader + " header");
            if (!path.StartsWith("/cmd/")) throw new LinkException(404, "POST to /cmd/<name>");

            string name = path.Substring("/cmd/".Length);
            JObject args = ReadArguments(request);
            Cmd cmd = Commands.Find(name);
            if (cmd == null) throw new LinkException(404, "unknown command '" + name + "'; GET /describe lists them");
            if (cmd.OffMainThread) return Success(cmd.Handler(args));

            Job job = MainThread.Submit(() => cmd.Handler(args));
            if (!job.Finished.Wait(CommandWaitMilliseconds)) throw new LinkException(504, "main thread did not answer (game paused or unfocused?)");
            if (job.Error != null)
            {
                Exception inner = job.Error is System.Reflection.TargetInvocationException && job.Error.InnerException != null ? job.Error.InnerException : job.Error;
                throw new LinkException(400, inner.Message);
            }
            return Success(job.Result);
        }

        private static JObject ReadArguments(HttpListenerRequest request)
        {
            string text;
            using (var reader = new StreamReader(request.InputStream, Encoding.UTF8)) text = reader.ReadToEnd();
            if (string.IsNullOrWhiteSpace(text)) return new JObject();
            try { return JObject.Parse(text); }
            catch (Exception ex) { throw new LinkException(400, "body is not a JSON object: " + ex.Message); }
        }

        private static object ReadEvents(System.Collections.Specialized.NameValueCollection query)
        {
            long since = query["since"] != null ? long.Parse(query["since"]) : 0;
            int wait = query["wait"] != null ? int.Parse(query["wait"]) : 0;
            int limit = query["limit"] != null ? int.Parse(query["limit"]) : 500;
            string type = query["type"];
            return EventLog.Read(since, Math.Min(wait, MaximumLongPollMilliseconds), limit, type);
        }
    }

    public class LinkException : Exception
    {
        public int Status;
        public LinkException(int status, string message) : base(message) { Status = status; }
    }
}
