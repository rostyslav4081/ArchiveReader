using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
    async void OpenBooks(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(busy)return;await SaveCurrent();var window=new BooksWindow(current?.Id,OcrSettings(),Call){Owner=this};window.ShowDialog();await RefreshPages(window.SelectedPageId);if(window.SelectedPageId!=null){current=allPages.FirstOrDefault(p=>p.Id==window.SelectedPageId);if(current!=null)await LoadPage(current);if(window.SelectedRecordId!=null && Records.Items.Cast<RecordItem>().FirstOrDefault(r=>r.Data["id"]?.ToString()==window.SelectedRecordId) is RecordItem record){loading=true;Records.SelectedItem=record;Fill(record.Data);loading=false;}}});
    async void OpenResearch(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(current==null || busy)return;await SaveCurrent();new ResearchWindow(current.Id,Call){Owner=this}.ShowDialog();});
    async void OpenOperations(object sender,RoutedEventArgs e)=>await Guard(async()=>
    {
        if(busy)return;await SaveCurrent();var window=new OperationsWindow(OcrSettings(),Call){Owner=this};window.ShowDialog();
        if(window.SelectedPageId!=null){await RefreshPages(window.SelectedPageId);current=allPages.FirstOrDefault(p=>p.Id==window.SelectedPageId);if(current!=null){await LoadPage(current);new WorkbenchWindow(current,Call,ModelPath.Text){Owner=this}.ShowDialog();}}
        else{await RefreshPages();if(current!=null)await LoadPage(current);}
    });
    async void OpenExtraction(object sender,RoutedEventArgs e)=>await Guard(async()=>
    {
        if(current==null || busy)return;await SaveCurrent();var window=new ExtractionWindow(current.Id,recordId,Call){Owner=this};window.ShowDialog();
        if(window.SavedRecordId!=null){await LoadPage(current);if(Records.Items.Cast<RecordItem>().FirstOrDefault(r=>r.Data["id"]?.ToString()==window.SavedRecordId) is RecordItem selected){loading=true;Records.SelectedItem=selected;Fill(selected.Data);loading=false;}}
    });
    async void OpenGenealogy(object sender,RoutedEventArgs e)=>await Guard(async()=>
    {
        if(busy)return;await SaveCurrent();var window=new GenealogyWindow(current?.Id,Call){Owner=this};window.ShowDialog();
        if(window.SelectedPageId!=null){await RefreshPages(window.SelectedPageId);current=allPages.FirstOrDefault(p=>p.Id==window.SelectedPageId);if(current!=null)await LoadPage(current);if(window.SelectedRecordId!=null && Records.Items.Cast<RecordItem>().FirstOrDefault(r=>r.Data["id"]?.ToString()==window.SelectedRecordId) is RecordItem record){loading=true;Records.SelectedItem=record;Fill(record.Data);loading=false;}}
    });
}
