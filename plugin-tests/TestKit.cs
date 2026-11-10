using System;
using System.Collections.Generic;

namespace CasualtiesLink.Tests
{
    public class AssertionFailed : Exception
    {
        public AssertionFailed(string message) : base(message) { }
    }

    public static class Check
    {
        public static void True(bool condition, string message)
        {
            if (!condition) throw new AssertionFailed(message);
        }

        public static void False(bool condition, string message)
        {
            if (condition) throw new AssertionFailed(message);
        }

        public static void Equal<T>(T expected, T actual, string message = "")
        {
            if (!EqualityComparer<T>.Default.Equals(expected, actual))
                throw new AssertionFailed(message + " expected " + Show(expected) + " but was " + Show(actual));
        }

        public static void Null(object value, string message)
        {
            if (value != null) throw new AssertionFailed(message + " expected null");
        }

        public static void Refused(Refusal refusal, int status, string message)
        {
            if (refusal == null) throw new AssertionFailed(message + " expected a refusal with status " + status + " but the request was allowed");
            if (refusal.Status != status) throw new AssertionFailed(message + " expected status " + status + " but was " + refusal.Status);
        }

        private static string Show(object value)
        {
            return value == null ? "null" : "'" + value + "'";
        }
    }

    public class TestCase
    {
        public string Name;
        public Action Body;
    }

    public class TestSuite
    {
        private readonly List<TestCase> cases = new List<TestCase>();

        public void Add(string name, Action body)
        {
            cases.Add(new TestCase { Name = name, Body = body });
        }

        public int Run()
        {
            int failed = 0;
            foreach (var testCase in cases)
            {
                try
                {
                    testCase.Body();
                    Console.WriteLine("ok    " + testCase.Name);
                }
                catch (Exception ex)
                {
                    failed++;
                    Console.WriteLine("FAIL  " + testCase.Name + ": " + ex.Message);
                }
            }
            Console.WriteLine("ran " + cases.Count + " plugin tests, " + failed + " failed");
            return failed == 0 ? 0 : 1;
        }
    }
}
