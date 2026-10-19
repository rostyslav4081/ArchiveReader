using System.Diagnostics;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using Microsoft.Win32;

namespace ArchiveReader;
public record BackupSnapshot(JsonObject Data)
{
    public string Label=>$"{DateTimeOffset.Parse(Data["created"]!.ToString()).ToLocalTime():g} · {Localizer.Text("Документів")}: {Data["documents"]} · {Data["bytes"]!.GetValue<long>()/1048576.0:F1} MB";
}
public partial class BackupWindow:Window
{
    readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;
    string? selectedVault; bool working;
    static string T(string value)=>Localizer.Text(value);
    public BackupWindow(Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker)
    {
        this.worker=worker; InitializeComponent(); Localizer.Apply(this,Localizer.Language);
        Closing+=(_,e)=>{if(working) e.Cancel=true;}; Loaded+=async (_,_)=>await Run(async()=>
        {
            await Refresh();
            if(Environment.GetCommandLineArgs().Contains("--smoke-backups"))
            {
                await Call("backup_create");await Refresh();UpdateLayout();
                var shot=new System.Windows.Media.Imaging.RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,System.Windows.Media.PixelFormats.Pbgra32);shot.Render(this);
                var png=new System.Windows.Media.Imaging.PngBitmapEncoder();png.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(shot));
                var folder=Environment.GetEnvironmentVariable("ARCHIVEREADER_DATA")!;
                using(var file=File.Create(Path.Combine(folder,"backup-window.png")))png.Save(file);
                _ = Dispatcher.BeginInvoke(new Action(Close));
            }
        });
    }
    Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,default);
    async Task Run(Func<Task> action)
    {
        if(working) return; working=true; IsEnabled=false;
        try { await action(); }
        catch(Exception ex){Report.Text=T("Помилка: ")+T(ex.Message);}
        finally{working=false;IsEnabled=true;}
    }
    async Task Refresh()
    {
        var list=await Call("backup_list"); VaultPath.Text=list["vault"]!.ToString(); selectedVault=VaultPath.Text;
        Automatic.IsChecked=list["enabled"]!.GetValue<bool>(); Snapshots.ItemsSource=list["snapshots"]!.AsArray().Select(n=>new BackupSnapshot(n!.AsObject())).ToList(); Snapshots.SelectedIndex=0;
    }
    void ChooseVault(object sender,RoutedEventArgs e)
    {var dialog=new OpenFolderDialog{Title=T("Папка резервних копій")}; if(dialog.ShowDialog()==true) {selectedVault=dialog.FolderName;VaultPath.Text=selectedVault;} }
    async Task Persist()=>await Call("settings",new(){["values"]=new JsonObject{["backupDirectory"]=selectedVault,["autoBackup"]=Automatic.IsChecked==true}});
    async void SaveSettings(object sender,RoutedEventArgs e)=>await Run(async()=>{await Persist();await Refresh();Report.Text=T("Налаштування копій збережено.");});
    async void CreateBackup(object sender,RoutedEventArgs e)=>await Run(async()=>{await Persist();Report.Text=T("Створення та перевірка копії…");await Call("backup_create");await Refresh();Report.Text=T("Резервну копію створено й перевірено.");});
    async void RestoreBackup(object sender,RoutedEventArgs e)
    {if(Snapshots.SelectedItem is BackupSnapshot snapshot) await Restore(snapshot.Data["path"]!.ToString());}
    async void RestoreOther(object sender,RoutedEventArgs e)
    {var dialog=new OpenFileDialog{Title=T("Виберіть manifest.json резервної копії"),Filter="Backup manifest|manifest.json"};if(dialog.ShowDialog()==true)await Restore(dialog.FileName);}
    async Task Restore(string manifest)
    {
        var dialog=new OpenFolderDialog{Title=T("Батьківська папка для відновленої бібліотеки")};if(dialog.ShowDialog()!=true)return;
        var destination=Path.Combine(dialog.FolderName,"ArchiveReader-restored-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N")[..6]);
        await Run(async()=>
        {
            Report.Text=T("Перевірка та відновлення копії…");
            await Call("backup_restore",new(){["path"]=manifest,["destination"]=destination});
            // PowerShell literal quoting preserves apostrophes; avoid interpolating paths into cmd code.
            string Quote(string value)=>"'"+value.Replace("'","''")+"'";
            var executable=Environment.ProcessPath ?? Path.Combine(AppContext.BaseDirectory,"ArchiveReader.exe");
            File.WriteAllText(Path.Combine(destination,"Open-RestoredLibrary.ps1"),"$env:ARCHIVEREADER_DATA="+Quote(destination)+"\r\nStart-Process -FilePath "+Quote(executable)+" -WindowStyle Hidden\r\n",new System.Text.UTF8Encoding(true));
            File.WriteAllText(Path.Combine(destination,"Open-RestoredLibrary.cmd"),"@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%~dp0Open-RestoredLibrary.ps1\"\r\n");
            Report.Text=T("Бібліотеку відновлено в окрему папку: ")+destination;
            Process.Start(new ProcessStartInfo{FileName=destination,UseShellExecute=true});
        });
    }
}
