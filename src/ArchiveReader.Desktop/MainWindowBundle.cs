using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenBundle(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(busy)return;await SaveCurrent();new ResearchBundleWindow(Call){Owner=this}.ShowDialog();});
}
