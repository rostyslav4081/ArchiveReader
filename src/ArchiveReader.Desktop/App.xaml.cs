using System.Windows;
namespace ArchiveReader;
public partial class App : Application
{
    System.Threading.Mutex? instance;
    protected override void OnStartup(StartupEventArgs e)
    {
        instance = new System.Threading.Mutex(true, "Local\\ArchiveReader-LocalLibrary", out bool created);
        if (!created) { MessageBox.Show("ArchiveReader уже відкрито."); Shutdown(); return; }
        base.OnStartup(e);
    }
    protected override void OnExit(ExitEventArgs e) { instance?.Dispose(); base.OnExit(e); }
}
