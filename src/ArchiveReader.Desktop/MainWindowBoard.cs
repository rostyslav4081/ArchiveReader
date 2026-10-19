using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenBoard(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(busy)return;await SaveCurrent();new BoardWindow(Call){Owner=this}.ShowDialog();});
}
