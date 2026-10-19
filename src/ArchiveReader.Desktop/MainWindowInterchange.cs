using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenInterchange(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(busy||current==null)return;await SaveCurrent();new InterchangeWindow(current.Id,Call){Owner=this}.ShowDialog();await LoadPage(current);});
}
