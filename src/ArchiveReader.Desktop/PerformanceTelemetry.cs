using System.Diagnostics;
using System.IO;
using System.Text.Json;
namespace ArchiveReader;
internal static class PerformanceTelemetry
{
 static readonly object gate=new();
 internal static void Record(string root,string command,string transport,double milliseconds,string? failure)
 {
  try{lock(gate){var folder=Path.Combine(root,"diagnostics");Directory.CreateDirectory(folder);var path=Path.Combine(folder,"request-timings.jsonl");if(File.Exists(path)&&new FileInfo(path).Length>2*1024*1024)File.Move(path,path+".previous",true);File.AppendAllText(path,JsonSerializer.Serialize(new{utc=DateTimeOffset.UtcNow,command,transport,elapsed_ms=Math.Round(milliseconds,3),success=failure==null,failure,pid=Environment.ProcessId})+Environment.NewLine);}}
  catch(IOException){}catch(UnauthorizedAccessException){}
 }
}
