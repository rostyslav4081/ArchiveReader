using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
namespace ArchiveReader;
public sealed class RegionPicker:Window
{
 public JsonArray? Bounds{get;private set;}
 public RegionPicker(string path)
 {
  Title=Localizer.Text("Вибрати фрагмент");Width=850;Height=760;WindowStartupLocation=WindowStartupLocation.CenterOwner;
  var bitmap=new BitmapImage(new Uri(path));var canvas=new Canvas{Width=700,Height=700.0*bitmap.PixelHeight/bitmap.PixelWidth,Background=Brushes.White};canvas.Children.Add(new Image{Source=bitmap,Width=canvas.Width,Height=canvas.Height});
  var outline=new Rectangle{Stroke=Brushes.Red,StrokeThickness=2,IsHitTestVisible=false};canvas.Children.Add(outline);Point? start=null;Rect? selected=null;
  canvas.MouseLeftButtonDown+=(_,e)=>{start=e.GetPosition(canvas);canvas.CaptureMouse();};
  canvas.MouseMove+=(_,e)=>{if(start==null||e.LeftButton!=MouseButtonState.Pressed)return;var p=e.GetPosition(canvas);p.X=Math.Clamp(p.X,0,canvas.Width);p.Y=Math.Clamp(p.Y,0,canvas.Height);selected=new Rect(start.Value,p);outline.Width=selected.Value.Width;outline.Height=selected.Value.Height;Canvas.SetLeft(outline,selected.Value.X);Canvas.SetTop(outline,selected.Value.Y);};
  canvas.MouseLeftButtonUp+=(_,_)=>{start=null;canvas.ReleaseMouseCapture();};
  var save=new Button{Content=Localizer.Text("Зберегти"),Height=40};save.Click+=(_,_)=>{if(selected is not Rect r||r.Width/canvas.Width<.002||r.Height/canvas.Height<.002)return;Bounds=new JsonArray(r.X/canvas.Width,r.Y/canvas.Height,r.Width/canvas.Width,r.Height/canvas.Height);DialogResult=true;};
  var panel=new DockPanel();DockPanel.SetDock(save,Dock.Bottom);panel.Children.Add(save);panel.Children.Add(new ScrollViewer{Content=canvas,HorizontalScrollBarVisibility=ScrollBarVisibility.Auto,VerticalScrollBarVisibility=ScrollBarVisibility.Auto});Content=panel;
 }
}
