using System.Windows.Threading;
namespace ArchiveReader;
public partial class MainWindow
{
 DispatcherTimer? indexTimer;readonly CancellationTokenSource indexingCancellation=new();bool indexing;
 protected override void OnContentRendered(EventArgs e)
 {
  base.OnContentRendered(e);
  if(Environment.GetCommandLineArgs().Contains("--smoke-test"))return;
  indexTimer=new DispatcherTimer{Interval=TimeSpan.FromSeconds(2)};
  indexTimer.Tick+=async(_,_)=>await AdvanceIndex();indexTimer.Start();
  Closed+=(_,_)=>{indexTimer.Stop();indexingCancellation.Cancel();};
  _=AdvanceIndex();
 }
 async Task AdvanceIndex()
 {
  if(indexing||indexingCancellation.IsCancellationRequested)return;
  indexing=true;
  try{var result=await Call("index_step",new(){["limit"]=25,["budget_ms"]=150},indexingCancellation.Token);if(indexTimer!=null)indexTimer.Interval=TimeSpan.FromSeconds(result["complete"]?.GetValue<bool>()==true?10:2);}
  catch(OperationCanceledException){}
  catch(Exception){if(indexTimer!=null)indexTimer.Interval=TimeSpan.FromSeconds(30);}
  finally{indexing=false;}
 }
}
