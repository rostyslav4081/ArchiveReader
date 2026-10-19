using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenShapeSearch(object s,RoutedEventArgs e)=>await Guard(async()=>{if(current==null||busy)return;await SaveCurrent();new ShapeSearchWindow(current.Id,Call){Owner=this}.ShowDialog();});
}
