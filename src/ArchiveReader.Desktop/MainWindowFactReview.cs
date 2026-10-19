using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenFactReview(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(current==null||busy||recordId==null)return;await SaveCurrent();var window=new FactReviewWindow(current.Id,recordId,Call){Owner=this};window.ShowDialog();if(window.SelectedPageId!=null){await RefreshPages(window.SelectedPageId);current=allPages.FirstOrDefault(p=>p.Id==window.SelectedPageId);if(current!=null){await LoadPage(current);if(Records.Items.Cast<RecordItem>().FirstOrDefault(r=>r.Data["id"]?.ToString()==window.SelectedRecordId) is RecordItem selected){loading=true;Records.SelectedItem=selected;Fill(selected.Data);loading=false;}}}});
}
