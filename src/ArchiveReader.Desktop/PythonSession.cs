using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json.Nodes;

namespace ArchiveReader;

/// <summary>One serial, bounded inference process owned by this application.</summary>
internal sealed class PythonSession:IDisposable
{
 readonly string python,root,appDirectory;
 readonly SemaphoreSlim gate=new(1,1);
 readonly object sync=new();
 readonly StringBuilder stderr=new();
 readonly Timer idleTimer;
 Process? process;
 DateTime lastUsed=DateTime.UtcNow;
 bool active,disposed;
 int requests;
 const int MaxRequests=24;
 static readonly TimeSpan IdleTimeout=TimeSpan.FromSeconds(90);

 public PythonSession(string python,string root,string appDirectory)
 {
  this.python=python;this.root=root;this.appDirectory=appDirectory;
  idleTimer=new Timer(_=>{lock(sync){if(!active&&process!=null&&DateTime.UtcNow-lastUsed>=IdleTimeout)StopLocked();}},null,TimeSpan.FromSeconds(15),TimeSpan.FromSeconds(15));
 }

 Process StartLocked()
 {
  if(process!=null&&(!process.HasExited)&&requests<MaxRequests)return process;
  StopLocked();lock(stderr)stderr.Clear();requests=0;
  var start=new ProcessStartInfo(python){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=appDirectory,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardInputEncoding=new UTF8Encoding(false),StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
  start.ArgumentList.Add("-X");start.ArgumentList.Add("utf8");start.ArgumentList.Add("-u");start.ArgumentList.Add(Path.Combine(appDirectory,"model_session.py"));
  start.Environment["PYTHONUTF8"]="1";start.Environment["ARCHIVEREADER_MODEL_SESSION"]="1";
  process=Process.Start(start)??throw new Exception(Localizer.Text("Не вдалося запустити Python."));
  process.ErrorDataReceived+=(_,e)=>{if(e.Data==null)return;lock(stderr){stderr.AppendLine(e.Data);if(stderr.Length>65536)stderr.Remove(0,stderr.Length-65536);}};
  process.BeginErrorReadLine();return process;
 }

 void StopLocked()
 {
  if(process==null)return;
  try{if(!process.HasExited)process.Kill(entireProcessTree:true);}catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}
  process.Dispose();process=null;requests=0;
 }

 void Kill(Process owned)
 {
  lock(sync){if(ReferenceEquals(process,owned))StopLocked();}
 }

 public async Task<JsonNode> CallAsync(string command,JsonObject? args=null,CancellationToken token=default)
 {
  // A single in-flight request keeps model state and JSONL replies in order.
  await gate.WaitAsync(token);
  Process? owned=null;
  try
  {
   lock(sync){ObjectDisposedException.ThrowIf(disposed,this);active=true;owned=StartLocked();}
   var request=args?.DeepClone().AsObject()??new JsonObject();var ident=Guid.NewGuid().ToString("N");
   request["command"]=command;request["root"]=root;request["request_id"]=ident;
   var seconds=900;
   if(request["timeout"] is JsonValue value&&value.TryGetValue<int>(out var configured))seconds=Math.Clamp(configured,1,7200);
   using var timeout=CancellationTokenSource.CreateLinkedTokenSource(token);timeout.CancelAfter(TimeSpan.FromSeconds(seconds));
   // Interrupt the owned process tree so native inference cannot outlive cancellation.
   using var cancel=timeout.Token.Register(()=>Kill(owned));
   try
   {
    await owned.StandardInput.WriteLineAsync(request.ToJsonString().AsMemory(),timeout.Token);
    await owned.StandardInput.FlushAsync(timeout.Token);
    var raw=await owned.StandardOutput.ReadLineAsync(timeout.Token);
    if(raw==null)throw new IOException("Inference session closed without a reply.");
    var reply=JsonNode.Parse(raw)??throw new IOException("Invalid inference reply.");
    if(reply["request_id"]?.ToString()!=ident)throw new IOException("Mismatched inference request ID.");
    lock(sync){requests++;lastUsed=DateTime.UtcNow;}
    if(reply["session"]?["restart_after_reply"]?.GetValue<bool>()==true)Kill(owned);
    if(reply["ok"]?.GetValue<bool>()!=true)throw new PythonReplyException(Localizer.Text(reply["error"]?.ToString()??"Python error"));
    return reply["result"]?.DeepClone()??JsonValue.Create((string?)null)!;
   }
   catch(Exception) when(timeout.IsCancellationRequested)
   {
    Kill(owned);token.ThrowIfCancellationRequested();throw new TimeoutException(Localizer.Text("Перевищено час очікування рушія. Повторіть спробу."));
   }
   catch(PythonReplyException){throw;}
   catch(Exception ex)
   {
    Kill(owned);
    var folder=Path.Combine(root,"diagnostics");Directory.CreateDirectory(folder);var file=Path.Combine(folder,$"session-{DateTime.UtcNow:yyyyMMdd-HHmmss}-{ident}.log");string tail;lock(stderr)tail=stderr.ToString();
    // Store diagnostics only, never request payloads or recognized private text.
    await File.WriteAllTextAsync(file,$"Command: {command}\nPython: {python}\nTransport: JSONL\nError: {ex.Message}\nSTDERR:\n{tail}",Encoding.UTF8);
    throw new IOException(Localizer.Text("Рушій не повернув відповідь. Журнал")+": "+file,ex);
   }
  }
  finally{lock(sync){active=false;lastUsed=DateTime.UtcNow;}gate.Release();}
 }

 public void Dispose(){lock(sync){if(disposed)return;disposed=true;idleTimer.Dispose();StopLocked();}GC.SuppressFinalize(this);}
 sealed class PythonReplyException(string message):Exception(message){}
}
