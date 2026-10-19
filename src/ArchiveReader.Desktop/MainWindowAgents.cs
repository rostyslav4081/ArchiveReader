using System.Windows;
namespace ArchiveReader;
public partial class MainWindow
{
 async void OpenAgents(object sender,RoutedEventArgs e)=>await Guard(async()=>{if(current==null||busy)return;await SaveCurrent();new AgentWindow(current.Id,Call,ModelPath.Text){Owner=this}.ShowDialog();});
}
