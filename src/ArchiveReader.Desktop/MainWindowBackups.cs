using System.Windows;
using System.Windows.Threading;

namespace ArchiveReader;
public partial class MainWindow
{
    readonly DispatcherTimer backupTimer=new(){Interval=TimeSpan.FromMinutes(15)};
    bool backupBusy;
    async Task InitializeBackups()
    {
        backupTimer.Tick+=async (_,_)=>await AutomaticBackup();
        Closed+=(_,_)=>backupTimer.Stop(); backupTimer.Start();
        await AutomaticBackup();
    }
    async Task AutomaticBackup()
    {
        if(backupBusy || busy || switching) return;
        backupBusy=true;
        var previous=Status.Text; var progress=T("Створення та перевірка копії…"); Status.Text=progress;
        try { await Call("backup_create",new(){["automatic"]=true}); if(Status.Text==progress) Status.Text=previous; }
        catch(Exception ex) { Status.Text=T("Не вдалося створити резервну копію: ")+T(ex.Message); }
        finally { backupBusy=false; }
    }
    async void OpenBackups(object sender,RoutedEventArgs e)=>await Guard(async()=>
    {
        if(busy || backupBusy) { Status.Text=T("Дочекайтеся завершення поточної обробки."); return; }
        await SaveCurrent(); new BackupWindow(Call){Owner=this}.ShowDialog();
    });
}
