using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenRecognitionWorkflow(object sender,RoutedEventArgs e)=>await Guard(async()=>
 {
  if(current==null||busy)return;await SaveCurrent();var engine=OcrSettings()["engine"]!.ToString();var window=new RecognitionWorkflowWindow(current.Id,engine,Call){Owner=this};window.ShowDialog();
  switch(window.Action)
  {
   case "historical":new HistoricalReadingWindow(current.Id,Call){Owner=this}.ShowDialog();break;
   case "layout":new WorkbenchWindow(current,Call,engine=="kraken"?ModelPath.Text:""){Owner=this}.ShowDialog();break;
   case "tutor":new TutorWindow(current.Id,engine=="kraken"?ModelPath.Text:"",Call){Owner=this}.ShowDialog();break;
   case "corpus":new CorpusWindow(current.Id,engine=="kraken"?ModelPath.Text:"",Call){Owner=this}.ShowDialog();break;
   case "models":
    var models=new ModelCatalogWindow(python,Call){Owner=this};
    if(models.ShowDialog()==true&&models.SelectedModel!=null){OcrEngine.SelectedIndex=models.SelectedEngine=="paddle"?3:0;ModelPath.Text=models.SelectedModel;await Call("settings",new(){["values"]=OcrSettings()});}
    break;
  }
  await LoadPage(current);
 });
}
