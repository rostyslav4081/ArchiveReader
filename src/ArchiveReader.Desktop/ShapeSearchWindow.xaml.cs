using System.Diagnostics;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
namespace ArchiveReader;
public partial class ShapeSearchWindow:Window
{
 readonly string page;readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;JsonArray? rect;string? report;CancellationTokenSource? work;bool busy;
 public ShapeSearchWindow(string page,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker){this.page=page;this.worker=worker;InitializeComponent();Localizer.Apply(this,Localizer.Language);Closing+=(_,_)=>work?.Cancel();}
 static BitmapImage Bitmap(string path){var b=new BitmapImage();b.BeginInit();b.CacheOption=BitmapCacheOption.OnLoad;b.UriSource=new Uri(path);b.EndInit();b.Freeze();return b;}
 async Task Run(Func<Task> action){if(busy)return;busy=true;work=new();SearchButton.IsEnabled=false;try{await action();}catch(OperationCanceledException){Status.Text=Localizer.Text("Обробку зупинено. Збережені результати залишилися в бібліотеці.");}catch(Exception e){Status.Text=e.Message;}finally{busy=false;work.Dispose();work=null;SearchButton.IsEnabled=rect!=null;}}
 Task<JsonNode> Call(string command,JsonObject args)=>worker(command,args,work?.Token??default);
 async void Pick(object s,RoutedEventArgs e)=>await Run(async()=>{var r=await Call("render",new(){["id"]=page,["whole"]=true,["full"]=true});var picker=new RegionPicker(r["path"]!.ToString()){Owner=this};if(picker.ShowDialog()!=true)return;rect=picker.Bounds;var b=Bitmap(r["path"]!.ToString());int x=(int)(rect![0]!.GetValue<double>()*b.PixelWidth),y=(int)(rect[1]!.GetValue<double>()*b.PixelHeight),w=Math.Max(1,(int)(rect[2]!.GetValue<double>()*b.PixelWidth)),h=Math.Max(1,(int)(rect[3]!.GetValue<double>()*b.PixelHeight));Query.Source=new CroppedBitmap(b,new Int32Rect(x,y,Math.Min(w,b.PixelWidth-x),Math.Min(h,b.PixelHeight-y)));Matches.ItemsSource=null;Candidate.Source=null;report=null;ReportButton.IsEnabled=false;});
 async void Search(object s,RoutedEventArgs e)=>await Run(async()=>{if(rect==null)return;var r=await Call("shape_search",new(){["id"]=page,["rect"]=rect.DeepClone()});Matches.ItemsSource=r["results"]!.AsArray().Select((v,n)=>new GenealogyRow(v!.AsObject(),$"{n+1}. {v["document"]} · {v["number"]}")).ToList();report=r["report"]!.ToString();ReportButton.IsEnabled=true;Status.Text=Localizer.Format("Переглянуто ділянок: {0}; фрагментів: {1}. Пошук обмежений, точність не виміряна.",r["scanned_regions"],r["windows"]);});
 void Select(object s,SelectionChangedEventArgs e){if(Matches.SelectedItem is not GenealogyRow row)return;Candidate.Source=Bitmap(row.Data["path"]!.ToString());Details.Text=Localizer.Text("Схожість форми не доводить спільного писаря чи прочитання.")+"\n\nDTW: "+row.Data["distance"]+"\n\n"+Localizer.Text(row.Data["text_status"]!.ToString()=="human_confirmed_whole_region"?"Підтверджений текст цілого рядка":"Неперевірений текст цілого рядка")+"\n"+row.Data["whole_region_text"];}
 void Stop(object s,RoutedEventArgs e)=>work?.Cancel();
 void Report(object s,RoutedEventArgs e){if(report!=null)Process.Start(new ProcessStartInfo(report){UseShellExecute=true});}
}
