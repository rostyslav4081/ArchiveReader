using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Input;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
namespace ArchiveReader;
public partial class FactCropWindow:Window
{
    readonly JsonObject mention;readonly string fact;readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;Point? start;Rect? rect;
    public FactCropWindow(JsonObject mention,string fact,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker)
    {this.mention=mention;this.fact=fact;this.worker=worker;InitializeComponent();Loaded+=async(_,_)=>{Localizer.Apply(this,Localizer.Language);try{var result=await worker("fact_crop",new(){["mention"]=mention.DeepClone(),["whole"]=true},default);var image=new BitmapImage(new Uri(result["path"]!.ToString()));PageImage.Source=image;Surface.Height=PageImage.Height=700*image.PixelHeight/image.PixelWidth;}catch(Exception ex){Status.Text=Localizer.Text(ex.Message);}};}
    void Begin(object sender,MouseButtonEventArgs e){start=e.GetPosition(Surface);Surface.CaptureMouse();}
    void Move(object sender,MouseEventArgs e){if(start==null || e.LeftButton!=MouseButtonState.Pressed)return;var end=e.GetPosition(Surface);end.X=Math.Clamp(end.X,0,Surface.Width);end.Y=Math.Clamp(end.Y,0,Surface.Height);rect=new Rect(start.Value,end);Selection.Width=rect.Value.Width;Selection.Height=rect.Value.Height;Canvas.SetLeft(Selection,rect.Value.X);Canvas.SetTop(Selection,rect.Value.Y);}
    void End(object sender,MouseButtonEventArgs e){Move(sender,e);start=null;Surface.ReleaseMouseCapture();}
    async void Save(object sender,RoutedEventArgs e){if(rect is not Rect bounds)return;try{await worker("fact_crop",new(){["mention"]=mention.DeepClone(),["fact"]=fact,["rect"]=new JsonArray(bounds.X/Surface.Width,bounds.Y/Surface.Height,bounds.Width/Surface.Width,bounds.Height/Surface.Height)},default);DialogResult=true;}catch(Exception ex){Status.Text=Localizer.Text(ex.Message);}}
}
