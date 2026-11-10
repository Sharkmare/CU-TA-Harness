using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using UnityEngine;

namespace CasualtiesLink
{

    public class Deferred
    {
        public Func<bool> IsDone;
        public Func<object> GetResult;
        public float TimeoutSeconds = 60f;
        public string Waiting = "condition";
    }

    public class Job
    {
        public Func<object> Work;
        public readonly ManualResetEventSlim Finished = new ManualResetEventSlim(false);
        public object Result;
        public Exception Error;
        public Deferred Pending;
        public float Deadline;
    }

    public class MainThread : MonoBehaviour
    {
        private static readonly ConcurrentQueue<Job> Queue = new ConcurrentQueue<Job>();
        private static readonly List<Job> Waiting = new List<Job>();
        public static int FrameNumber;
        public static MainThread Instance;

        private void Awake() { Instance = this; }

        public static Job Submit(Func<object> work)
        {
            var job = new Job { Work = work };
            Queue.Enqueue(job);
            return job;
        }

        private void Update()
        {
            FrameNumber = Time.frameCount;
            int budget = 64;
            while (budget-- > 0 && Queue.TryDequeue(out Job job)) RunJob(job);
            PollWaiting();
            InputInjector.EndFrame();
            EventLog.PollGameState();
        }

        private static void RunJob(Job job)
        {
            try
            {
                object result = job.Work();
                if (result is Deferred deferred)
                {
                    job.Pending = deferred;
                    job.Deadline = Time.realtimeSinceStartup + deferred.TimeoutSeconds;
                    Waiting.Add(job);
                    return;
                }
                job.Result = result;
            }
            catch (Exception ex) { job.Error = ex; }
            job.Finished.Set();
        }

        private static void PollWaiting()
        {
            for (int i = Waiting.Count - 1; i >= 0; i--)
            {
                Job job = Waiting[i];
                try
                {
                    if (job.Pending.IsDone())
                    {
                        job.Result = job.Pending.GetResult();
                        Waiting.RemoveAt(i);
                        job.Finished.Set();
                    }
                    else if (Time.realtimeSinceStartup > job.Deadline)
                    {
                        job.Error = new TimeoutException("timed out waiting for " + job.Pending.Waiting);
                        Waiting.RemoveAt(i);
                        job.Finished.Set();
                    }
                }
                catch (Exception ex)
                {
                    job.Error = ex;
                    Waiting.RemoveAt(i);
                    job.Finished.Set();
                }
            }
        }
    }
}
