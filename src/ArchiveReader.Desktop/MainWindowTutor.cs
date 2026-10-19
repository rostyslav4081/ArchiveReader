using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenTutor(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(current==null)return;await SaveCurrent();new TutorWindow(current.Id,ModelPath.Text,Call){Owner=this}.ShowDialog();if(current!=null)await LoadPage(current);});
}
