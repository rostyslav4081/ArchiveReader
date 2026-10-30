using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
namespace ArchiveReader;
internal static class SmokeCapture
{
    internal static void Fail(Exception exception)
    {
        if(!Environment.GetCommandLineArgs().Contains("--smoke-roadmap")&&!Environment.GetCommandLineArgs().Contains("--smoke-tree"))return;
        File.WriteAllText(Path.Combine(Environment.GetEnvironmentVariable("ARCHIVEREADER_DATA")!,"roadmap-error.txt"),exception.ToString());Application.Current.Shutdown(1);
    }
    internal static void Save(Window window,string directory,string name)
    {
        window.UpdateLayout();var folder=Path.Combine(Environment.GetEnvironmentVariable("ARCHIVEREADER_DATA")!,directory);Directory.CreateDirectory(folder);
        var image=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);image.Render(window);
        var png=new PngBitmapEncoder();png.Frames.Add(BitmapFrame.Create(image));using var file=File.Create(Path.Combine(folder,name));png.Save(file);
    }
}
