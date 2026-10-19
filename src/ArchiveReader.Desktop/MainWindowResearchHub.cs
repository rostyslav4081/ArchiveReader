using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenResearchHub(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(busy||current==null)return;await SaveCurrent();var dialog=new ResearchHubWindow(current.Id,Call){Owner=this};dialog.ShowDialog();if(dialog.SelectedPageId!=null){await RefreshPages(dialog.SelectedPageId);current=allPages.FirstOrDefault(p=>p.Id==dialog.SelectedPageId);if(current!=null){await LoadPage(current);if(dialog.SelectedRecordId!=null && Records.Items.Cast<RecordItem>().FirstOrDefault(r=>r.Data["id"]?.ToString()==dialog.SelectedRecordId) is RecordItem selected){loading=true;Records.SelectedItem=selected;Fill(selected.Data);loading=false;}}}if(dialog.RequestedTool=="workbench"&&current!=null)new WorkbenchWindow(current,Call,ModelPath.Text){Owner=this}.ShowDialog();else if(dialog.RequestedTool=="books")new BooksWindow(current?.Id,OcrSettings(),Call){Owner=this}.ShowDialog();else if(dialog.RequestedTool=="research"&&current!=null)new ResearchWindow(current.Id,Call){Owner=this}.ShowDialog();});
}
