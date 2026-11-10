namespace CasualtiesLink.Tests
{
    public static class PathParserTests
    {
        public static void Register(TestSuite suite)
        {
            suite.Add("path parser: an empty or missing path has no tokens", () =>
            {
                Check.Equal(0, PathParser.Parse("").Count, "empty");
                Check.Equal(0, PathParser.Parse(null).Count, "null");
            });

            suite.Add("path parser: dots split names", () =>
            {
                var tokens = PathParser.Parse("skills.STR");
                Check.Equal(2, tokens.Count, "count");
                Check.Equal("skills", tokens[0].Name, "first");
                Check.Equal("STR", tokens[1].Name, "second");
                Check.Null(tokens[0].Index, "no index");
            });

            suite.Add("path parser: a number in brackets is a numeric index", () =>
            {
                var tokens = PathParser.Parse("limbs[3].bleedAmount");
                Check.Equal("limbs", tokens[0].Name, "name");
                Check.Equal((object)3L, tokens[0].Index, "index");
                Check.Equal("bleedAmount", tokens[1].Name, "next");
            });

            suite.Add("path parser: quoted text in brackets is a string key without the quotes", () =>
            {
                Check.Equal((object)"healingrate", PathParser.Parse("runSettings[\"healingrate\"]")[0].Index, "double quotes");
                Check.Equal((object)"healingrate", PathParser.Parse("runSettings['healingrate']")[0].Index, "single quotes");
            });

            suite.Add("path parser: unquoted text in brackets is a string key", () =>
                Check.Equal((object)"abc", PathParser.Parse("map[abc]")[0].Index, "key"));

            suite.Add("path parser: a bracket with no name indexes the target itself", () =>
            {
                var tokens = PathParser.Parse("[2]");
                Check.Equal("", tokens[0].Name, "name");
                Check.Equal((object)2L, tokens[0].Index, "index");
            });

            suite.Add("path parser: a negative number is still a number", () =>
                Check.Equal((object)(-1L), PathParser.Parse("items[-1]")[0].Index, "index"));
        }
    }
}
