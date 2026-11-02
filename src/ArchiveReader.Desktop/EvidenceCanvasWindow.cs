using System.Diagnostics;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace ArchiveReader;

/// <summary>A single zoomable board for the description and every attached document.</summary>
public sealed class EvidenceCanvasWindow : Window
{
    readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;
    readonly JsonObject selection;
    readonly Canvas board=new(){Background=new SolidColorBrush(Color.FromRgb(244,240,232))};
    readonly ScrollViewer viewport=new(){HorizontalScrollBarVisibility=ScrollBarVisibility.Auto,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
    readonly ScaleTransform scale=new(1,1);
    readonly TextBlock status=new(){Margin=new Thickness(12,8,8,8)};
    readonly List<(Border Card,Image Image,TextBlock State,JsonObject Data)> photos=[];
    readonly HashSet<string> loaded=[];
    readonly CancellationTokenSource lifetime=new();
    bool loading,ready;Point? drag;double dragX,dragY;
    static string T(string text)=>Localizer.Text(text);
    public EvidenceCanvasWindow(Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker,JsonObject selection)
    {
        this.worker=worker;this.selection=selection;
        Title=T("Опис і всі документи — спільне полотно");Width=1450;Height=940;MinWidth=900;MinHeight=600;
        WindowStartupLocation=WindowStartupLocation.CenterOwner;
        var root=new DockPanel();var tools=new WrapPanel{Background=Brushes.White,Margin=new Thickness(8)};
        void Action(string title,Action action){var b=new Button{Content=T(title),Padding=new Thickness(12,6,12,6),Margin=new Thickness(4)};b.Click+=(_,_)=>action();tools.Children.Add(b);}
        Action("−",()=>Zoom(scale.ScaleX/1.2));Action("+",()=>Zoom(scale.ScaleX*1.2));
        Action("За шириною",()=>Zoom((viewport.ViewportWidth-30)/board.Width));
        Action("Усе полотно",()=>Zoom(Math.Min((viewport.ViewportWidth-30)/board.Width,(viewport.ViewportHeight-30)/board.Height)));
        Action("100%",()=>Zoom(1));tools.Children.Add(status);DockPanel.SetDock(tools,Dock.Top);root.Children.Add(tools);
        board.LayoutTransform=scale;viewport.Content=board;root.Children.Add(viewport);Content=root;
        viewport.ScrollChanged+=async(_,_)=>await LoadVisible();
        viewport.PreviewMouseWheel+=(_,e)=>{if(Keyboard.Modifiers.HasFlag(ModifierKeys.Control)){Zoom(scale.ScaleX*(e.Delta>0?1.15:1/1.15));e.Handled=true;}};
        viewport.PreviewMouseDown+=(_,e)=>{if(e.ChangedButton!=MouseButton.Middle)return;drag=e.GetPosition(viewport);dragX=viewport.HorizontalOffset;dragY=viewport.VerticalOffset;viewport.CaptureMouse();e.Handled=true;};
        viewport.PreviewMouseMove+=(_,e)=>{if(drag is not Point start)return;var p=e.GetPosition(viewport);viewport.ScrollToHorizontalOffset(dragX+start.X-p.X);viewport.ScrollToVerticalOffset(dragY+start.Y-p.Y);};
        viewport.PreviewMouseUp+=(_,e)=>{if(e.ChangedButton==MouseButton.Middle){drag=null;viewport.ReleaseMouseCapture();}};
        Closed+=(_,_)=>lifetime.Cancel();Loaded+=async(_,_)=>await LoadBoard();
    }
    static TextBlock Text(string value,double size=14)=>new(){Text=value,FontSize=size,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,4,0,4)};
    void Place(UIElement element,double x,double y){Canvas.SetLeft(element,x);Canvas.SetTop(element,y);board.Children.Add(element);}
    void Zoom(double value)
    {
        if(!ready)return;double previous=scale.ScaleX;value=Math.Clamp(value,.02,2.5);
        double x=(viewport.HorizontalOffset+viewport.ViewportWidth/2)/previous,y=(viewport.VerticalOffset+viewport.ViewportHeight/2)/previous;
        scale.ScaleX=scale.ScaleY=value;viewport.UpdateLayout();viewport.ScrollToHorizontalOffset(Math.Max(0,x*value-viewport.ViewportWidth/2));viewport.ScrollToVerticalOffset(Math.Max(0,y*value-viewport.ViewportHeight/2));UpdateStatus();
    }
    void UpdateStatus()=>status.Text=$"{photos.Count} {T("фото")} · {scale.ScaleX:P0} · Ctrl + {T("колесо — масштаб; середня кнопка — пересування")}";
    async Task LoadBoard()
    {
        try
        {
            status.Text=T("Завантаження документів…");
            var data=await worker("genealogy_canvas",selection,lifetime.Token);if(lifetime.IsCancellationRequested)return;
            Title=data["title"]+" — "+T("Опис і всі документи");board.Width=1470;
            Place(new TextBlock{Text=data["title"]!.ToString(),FontSize=26,FontWeight=FontWeights.SemiBold,Width=1410,TextWrapping=TextWrapping.Wrap},28,24);
            var summary=new StackPanel();summary.Children.Add(Text(T("Опис"),20));
            summary.Children.Add(new TextBox{Text=data["description"]?.ToString(),IsReadOnly=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Height=540,BorderThickness=new Thickness(0),Background=Brushes.Transparent});
            summary.Children.Add(Text(T("Оригінали збережені. Натисни фото, щоб збільшити його; архівні дані вказані під кожним зображенням.")));
            Place(new Border{Width=350,Padding=new Thickness(20),Background=Brushes.White,CornerRadius=new CornerRadius(14),Child=summary},28,100);
            double y=100;
            foreach(var group in data["documents"]!.AsArray().Select(n=>n!.AsObject()).GroupBy(n=>n["group"]!.ToString()))
            {
                var heading=new TextBlock{Text=group.Key+$" ({group.Count()})",Width=1035,Height=64,TextWrapping=TextWrapping.Wrap,FontWeight=FontWeights.SemiBold,FontSize=17};Place(heading,410,y);y+=72;
                int index=0;
                foreach(var document in group)
                {
                    var panel=new StackPanel();var title=Text(document["title"]!.ToString(),15);title.FontWeight=FontWeights.SemiBold;title.Height=48;panel.Children.Add(title);
                    var picture=new Image{Width=298,Height=250,Stretch=Stretch.Uniform,Cursor=Cursors.Hand,ToolTip=T("Збільшити фото")};
                    picture.MouseLeftButtonDown+=async(_,_)=>await Enlarge(document);panel.Children.Add(picture);
                    var state=Text(T(document["missing"]!.GetValue<bool>()?"Оригінал не знайдено":"Фото завантажиться під час перегляду"));state.FontSize=11;panel.Children.Add(state);
                    panel.Children.Add(new TextBox{Text=document["citation"]!.ToString(),IsReadOnly=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Height=85,BorderThickness=new Thickness(0)});
                    panel.Children.Add(new TextBox{Text=document["text"]?.ToString(),IsReadOnly=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Height=85,BorderThickness=new Thickness(0)});
                    var buttons=new WrapPanel();var enlarge=new Button{Content=T("Збільшити фото"),Padding=new Thickness(8,5,8,5),Margin=new Thickness(2)};enlarge.Click+=async(_,_)=>await Enlarge(document);buttons.Children.Add(enlarge);
                    var link=document["source_url"]?.ToString();
                    if(Uri.TryCreate(link,UriKind.Absolute,out var uri)&&uri.Scheme is "https" or "http")
                    {
                        var source=new Button{Content=T(document["source_scope"]!.ToString()=="scan"?"Архівний скан":"Архівна справа"),Padding=new Thickness(8,5,8,5),Margin=new Thickness(2)};
                        source.Click+=(_,_)=>{try{Process.Start(new ProcessStartInfo(uri.AbsoluteUri){UseShellExecute=true});}catch(Exception ex){status.Text=ex.Message;}};buttons.Children.Add(source);
                    }
                    panel.Children.Add(buttons);
                    var card=new Border{Width=330,Height=690,Padding=new Thickness(16),Background=Brushes.White,CornerRadius=new CornerRadius(12),Child=panel};
                    Place(card,410+(index%3)*350,y+(index/3)*715);photos.Add((card,picture,state,document));index++;
                }
                y+=Math.Ceiling(index/3d)*715+32;
            }
            board.Height=Math.Max(820,y);ready=true;scale.ScaleX=scale.ScaleY=Math.Clamp((ActualWidth-60)/board.Width,.3,1);viewport.UpdateLayout();UpdateStatus();await LoadVisible();
            if(Environment.GetCommandLineArgs().Contains("--smoke-evidence-canvas")){while(loading)await Task.Delay(20);await Dispatcher.InvokeAsync(()=>{},System.Windows.Threading.DispatcherPriority.Render);SmokeCapture.Save(this,"genealogy-ui","evidence-canvas.png");Close();}
        }
        catch(OperationCanceledException){}catch(Exception ex){status.Text=T("Помилка: ")+ex.Message;SmokeCapture.Fail(ex);}
    }
    static BitmapImage Bitmap(string path,int width)
    {
        var image=new BitmapImage();image.BeginInit();image.CacheOption=BitmapCacheOption.OnLoad;image.DecodePixelWidth=width;image.UriSource=new Uri(path);image.EndInit();image.Freeze();return image;
    }
    async Task LoadVisible()
    {
        if(!ready||loading||lifetime.IsCancellationRequested)return;loading=true;
        try
        {
            foreach(var photo in photos)
            {
                if(lifetime.IsCancellationRequested)return;
                double top=Canvas.GetTop(photo.Card)*scale.ScaleY,left=Canvas.GetLeft(photo.Card)*scale.ScaleX;
                if(top>viewport.VerticalOffset+viewport.ViewportHeight+400||top+photo.Card.Height*scale.ScaleY<viewport.VerticalOffset-400||left>viewport.HorizontalOffset+viewport.ViewportWidth+200||left+photo.Card.Width*scale.ScaleX<viewport.HorizontalOffset-200)continue;
                string id=photo.Data["page"]!.ToString();if(!loaded.Add(id))continue;
                try
                {
                    string? path=photo.Data["image_path"]?.ToString();
                    if(path==null){var rendered=await worker("render",new(){["id"]=id},lifetime.Token);path=rendered["path"]!.ToString();}
                    var bitmap=await Task.Run(()=>Bitmap(path,620),lifetime.Token);if(lifetime.IsCancellationRequested)return;
                    photo.Image.Source=bitmap;photo.State.Text="";
                }
                catch(OperationCanceledException){return;}catch(Exception ex){photo.State.Text=T("Не вдалося відкрити фото: ")+ex.Message;}
            }
        }
        finally{loading=false;}
    }
    async Task Enlarge(JsonObject document)
    {
        try
        {
            var rendered=await worker("render",new(){["id"]=document["page"]!.ToString(),["full"]=true,["whole"]=true},lifetime.Token);
            var image=await Task.Run(()=>Bitmap(rendered["path"]!.ToString(),0),lifetime.Token);if(lifetime.IsCancellationRequested)return;
            var zoom=new ScaleTransform(1,1);var picture=new Image{Source=image,Stretch=Stretch.None,LayoutTransform=zoom};
            var scroll=new ScrollViewer{Content=picture,HorizontalScrollBarVisibility=ScrollBarVisibility.Auto,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
            scroll.PreviewMouseWheel+=(_,e)=>{if(!Keyboard.Modifiers.HasFlag(ModifierKeys.Control))return;zoom.ScaleX=zoom.ScaleY=Math.Clamp(zoom.ScaleX*(e.Delta>0?1.2:1/1.2),.05,4);e.Handled=true;};
            new Window{Owner=this,Title=document["title"]!.ToString(),Width=1150,Height=850,Content=scroll,WindowStartupLocation=WindowStartupLocation.CenterOwner}.ShowDialog();
        }
        catch(OperationCanceledException){}catch(Exception ex){status.Text=ex.Message;}
    }
}
