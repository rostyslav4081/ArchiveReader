using System.IO;

namespace ArchiveReader;

internal static class PythonRuntime
{
    public static string Resolve()
    {
        var configured = Environment.GetEnvironmentVariable("ARCHIVEREADER_PYTHON");
        if (!string.IsNullOrWhiteSpace(configured)) return configured;
        // Direct executable launches should use the same environment as the launcher.
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory != null; directory = directory.Parent)
        {
            var candidate = Path.Combine(directory.FullName, ".venv", "Scripts", "python.exe");
            if (File.Exists(candidate)) return candidate;
        }
        return "python";
    }
}
