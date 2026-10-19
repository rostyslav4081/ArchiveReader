using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenHistorical(object sender,RoutedEventArgs e)=>await Guard(async()=>
 {
  if(busy||current==null)return;
  await SaveCurrent();
  var window=new HistoricalReadingWindow(current.Id,Call){Owner=this};window.ShowDialog();
  if(window.RequestedRecognitionAnnotation is string region)
  {
   new WorkbenchWindow(current,Call,ModelPath.Text,region,true){Owner=this}.ShowDialog();
   await LoadPage(current);
  }
 });
}
