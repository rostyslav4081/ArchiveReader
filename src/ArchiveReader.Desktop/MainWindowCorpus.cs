using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenCorpus(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(busy)return;await SaveCurrent();new CorpusWindow(current?.Id,ModelPath.Text,Call){Owner=this}.ShowDialog();});
}
