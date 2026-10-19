using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;

namespace ArchiveReader;

public record LibraryRow(JsonObject Data,string Label);
public partial class LibraryWindow : Window
{
    readonly PageItem? page;
    readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker;
    CancellationTokenSource? work;
    bool busy;
    JsonObject? selected;
    string? frozenPath;
    public string? SelectedPageId { get; private set; }
    public string? SelectedRecordId { get; private set; }
    public string? SelectedRegionId { get; private set; }
    public int? SelectedLine { get; private set; }
    public string SearchQuery { get; private set; }="";
    static string T(string s)=>Localizer.Text(s);
    Task<JsonNode> Call(string command,JsonObject? args=null)=>worker(command,args,work?.Token ?? default);
    static string Source(string s)=>T(s switch { "record"=>"Запис", "correction"=>"Виправлений рядок", "region"=>"Ділянка", "line"=>"Рядок", "disagreement"=>"Є розбіжності", "missing"=>"Відсутній фрагмент", "damage"=>"Пошкодження", "error"=>"Помилка", _=>"OCR" });
    public LibraryWindow(PageItem? page,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> worker)
    {
        this.page=page; this.worker=worker; InitializeComponent();
        Loaded+=async (_,_)=>await Run(async()=>
        {
            Localizer.Apply(this,Localizer.Language);
            await LoadReview(); await LoadBenchmark();
            if(page!=null)
            {
                await LoadHistory(); await LoadTemplates();
                var pages=await Call("list_pages");
                TemplatePages.ItemsSource=pages.AsArray().Where(n=>n!["doc"]?.ToString()==page.Doc).Select(n=>new PageItem(n!["id"]!.ToString(),n["doc"]!.ToString(),n["num"]!.GetValue<int>(),n["name"]!.ToString(),n["path"]!.ToString(),n["status"]!.ToString())).ToList();
            }
            Status.Text=T("Готово");
            if(Environment.GetCommandLineArgs().Contains("--smoke-library"))
            {
                Query.Text="Joannes"; await LoadSearch();
                var folder=Environment.GetEnvironmentVariable("ARCHIVEREADER_DATA") ?? AppContext.BaseDirectory;
                Directory.CreateDirectory(System.IO.Path.Combine(folder,"library-ui"));
                Tabs.IsEnabled=true;
                for(int i=0;i<Tabs.Items.Count;i++)
                {
                    Tabs.SelectedIndex=i;
                    if(i==0 && ReviewRows.Items.Count>0) { ReviewRows.SelectedIndex=0; await ShowReview((LibraryRow)ReviewRows.Items[0]); }
                    if(i==1 && SearchRows.Items.Count>0) { SearchRows.SelectedIndex=0; await ShowSearch((LibraryRow)SearchRows.Items[0]); }
                    if(i==2 && HistoryRows.Items.Count>0) HistoryRows.SelectedIndex=0;
                    UpdateLayout();
                    var image=new RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,PixelFormats.Pbgra32); image.Render(this);
                    var png=new PngBitmapEncoder(); png.Frames.Add(BitmapFrame.Create(image));
                    using(var file=File.Create(System.IO.Path.Combine(folder,"library-ui",$"tab-{i}.png"))) png.Save(file);
                }
                Close();
            }
        });
        Closing+=(_,_)=>work?.Cancel();
    }
    async Task Run(Func<Task> action)
    {
        if(busy) return; busy=true; work=new(); Tabs.IsEnabled=false;
        try { await action(); }
        catch(OperationCanceledException) { Status.Text=T("Обробку зупинено. Збережені результати залишилися в бібліотеці."); }
        catch(Exception ex)
        {
            Status.Text=T(ex.Message);
            if(Environment.GetCommandLineArgs().Contains("--smoke-library")) { File.WriteAllText(System.IO.Path.Combine(AppContext.BaseDirectory,"library-error.log"),ex.ToString()); Application.Current.Shutdown(1); }
            else MessageBox.Show(this,T(ex.Message),T("Перевірка бібліотеки"));
        }
        finally { Tabs.IsEnabled=true; work.Dispose(); work=null; busy=false; }
    }
    void Cancel(object sender,RoutedEventArgs e)=>work?.Cancel();
    async Task LoadReview()
    {
        var rows=await Call("review_queue");
        ReviewRows.ItemsSource=rows.AsArray().Select(n=>new LibraryRow(n!.AsObject(),$"{Source(n["kind"]!.ToString())} · {n["name"]} · {T("Стор.")} {n["number"]}")).ToList();
    }
    async void RefreshReview(object sender,RoutedEventArgs e)=>await Run(LoadReview);
    async void Resolve(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(ReviewRows.SelectedItem is not LibraryRow row) return;
        await Call("review_resolve",new() { ["key"]=row.Data["key"]!.ToString(),["signature"]=row.Data["signature"]!.ToString() }); await LoadReview();
        selected=null; Details.Text=""; Status.Text=T("Розглянуто. Змінені результати з’являться в черзі знову.");
    });
    async void SelectReview(object sender,SelectionChangedEventArgs e)
    {
        if(busy || ReviewRows.SelectedItem is not LibraryRow row) return;
        await Run(()=>ShowReview(row));
    }
    async Task ShowReview(LibraryRow row)
    {
        selected=row.Data; DetailTitle.Text=row.Label; Snippet.Text=row.Data["text"]?.ToString() ?? "";
        Details.Text=string.Join("\n\n",(row.Data["predictions"]?.AsObject() ?? new JsonObject()).Select(p=>p.Key+": "+(p.Value?["text"] ?? p.Value?["error"])));
        await Preview(row.Data["page"]!.ToString(),row.Data["region"]?.ToString());
    }
    async Task Preview(string id,string? region=null)
    {
        var result=await Call("review_context",new() { ["id"]=id,["region"]=region });
        var image=new BitmapImage(); image.BeginInit(); image.CacheOption=BitmapCacheOption.OnLoad; image.UriSource=new Uri(result["path"]!.ToString()); image.EndInit(); image.Freeze();
        double width=Math.Min(500,380.0*image.PixelWidth/image.PixelHeight);
        ContextGrid.Width=ContextImage.Width=width; ContextImage.Source=image; ContextImage.Height=width*image.PixelHeight/image.PixelWidth; FocusOverlay.Children.Clear();
        if(result["focus"] is JsonArray focus)
        {
            var rect=new Rectangle { Width=focus[2]!.GetValue<double>()*width,Height=focus[3]!.GetValue<double>()*ContextImage.Height,Stroke=Brushes.Gold,StrokeThickness=3 };
            Canvas.SetLeft(rect,focus[0]!.GetValue<double>()*width); Canvas.SetTop(rect,focus[1]!.GetValue<double>()*ContextImage.Height); FocusOverlay.Children.Add(rect);
        }
    }
    async Task LoadSearch()
    {
        if(Environment.GetCommandLineArgs().Contains("--smoke-library"))await Call("index_step",new(){["limit"]=100});
        var result=await Call("library_search",new() { ["query"]=Query.Text,["refresh_limit"]=0 });
        SearchRows.ItemsSource=result["rows"]!.AsArray().Select(n=>new LibraryRow(n!.AsObject(),$"{n["name"]} · {T("Стор.")} {n["number"]} · {Source(n["source"]!.ToString())}\n{n["snippet"]}")).ToList();
        Status.Text=(result["limited"]!.GetValue<bool>()?T("Показано перші результати. Уточніть пошук."):T("Готово"))+" · "+Localizer.Format("Не розпізнано сторінок: {0}; помилок OCR: {1}. Фото й рукописи стають доступні для пошуку після розпізнавання.",result["coverage"]!["pending"],result["coverage"]!["errors"]);
        if(result["coverage"]?["index_remaining"]?.GetValue<int>() is int remaining && remaining>0)Status.Text+=" · "+Localizer.Format("Ще індексується сторінок: {0}. Результати поки неповні.",remaining);
    }
    async void Search(object sender,RoutedEventArgs e)=>await Run(LoadSearch);
    async void SelectSearch(object sender,SelectionChangedEventArgs e)
    {
        if(busy || SearchRows.SelectedItem is not LibraryRow row) return;
        await Run(()=>ShowSearch(row));
    }
    async Task ShowSearch(LibraryRow row)
    {
            selected=row.Data; DetailTitle.Text=$"{row.Data["name"]} · {T("Стор.")} {row.Data["number"]}"; Details.Text="";
            var text=row.Data["snippet"]!.ToString(); Snippet.Inlines.Clear();
            foreach(var part in text.Split('⟦'))
            {
                var chunks=part.Split('⟧',2);
                Snippet.Inlines.Add(new Run(chunks[0]) { Background=chunks.Length==2?Brushes.Gold:Brushes.Transparent });
                if(chunks.Length==2) Snippet.Inlines.Add(new Run(chunks[1]));
            }
            await Preview(row.Data["page"]!.ToString(),row.Data["source"]?.ToString()=="region"?row.Data["entity"]?.ToString():null);
    }
    void GoToSource(object sender,RoutedEventArgs e)
    {
        if(selected==null) return; SelectedPageId=selected["page"]?.ToString();
        var source=selected["source"]?.ToString();
        if(source=="record") SelectedRecordId=selected["entity"]?.ToString();
        if(source=="correction") SelectedLine=int.Parse(selected["entity"]!.ToString());
        SelectedRegionId=selected["region"]?.ToString() ?? (source=="region"?selected["entity"]?.ToString():null);
        SearchQuery=source!=null?Query.Text:""; Close();
    }
    async Task LoadHistory()
    {
        if(page==null) return;
        var rows=await Call("history_list",new() { ["id"]=page.Id });
        HistoryRows.ItemsSource=rows.AsArray().Select(n=>new LibraryRow(n!.AsObject(),$"{n["created"]} · {Source(n["kind"]!.ToString())} · {T(n["version"]!.ToString()=="before"?"До зміни":"Після зміни")} · {n["revision"]}")).ToList();
    }
    async void RefreshHistory(object sender,RoutedEventArgs e)=>await Run(LoadHistory);
    void SelectHistory(object sender,SelectionChangedEventArgs e)
    {
        if(HistoryRows.SelectedItem is not LibraryRow row) return;
        selected=null; DetailTitle.Text=row.Label; Snippet.Text="";
        var labels=new Dictionary<string,string> { ["kind"]="Тип ділянки",["person"]="Особа",["date"]="Дата",["text"]="Текст рядка або примітка",["rect"]="Межі ділянки",["verified"]="Перевірено за оригіналом",["label"]="Назва ділянки",["notes"]="Примітки",["related1"]="Батько / наречена",["related2"]="Мати / свідки",["place"]="Населений пункт",["house"]="№ будинку",["number"]="Номер запису",["age"]="Вік",["cause"]="Причина смерті" };
        Details.Text=string.Join("\n\n",row.Data["snapshot"]!.AsObject().Where(p=>labels.ContainsKey(p.Key)).Select(p=>T(labels[p.Key])+": "+p.Value));
    }
    async void Restore(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(page==null || HistoryRows.SelectedItem is not LibraryRow row) return;
        var args=new JsonObject { ["id"]=page.Id };
        foreach(var field in new[] { "kind","entity","revision","version","expected" }) args[field]=row.Data[field]!.DeepClone();
        await Call("history_restore",args); await LoadHistory(); await LoadReview(); Status.Text=T("Версію відновлено. Попередній стан залишився в історії.");
    });
    async Task LoadTemplates()
    {
        if(page==null) return; var rows=await Call("template_list",new() { ["id"]=page.Id });
        Templates.ItemsSource=rows.AsArray().Select(n=>new LibraryRow(n!.AsObject(),n["name"]!.ToString())).ToList(); Templates.SelectedIndex=0;
    }
    async void SaveTemplate(object sender,RoutedEventArgs e)=>await Run(async()=>
    { if(page==null) return; await Call("template_save",new() { ["id"]=page.Id,["name"]=TemplateName.Text }); await LoadTemplates(); Status.Text=T("Шаблон збережено."); });
    void SelectAllPages(object sender,RoutedEventArgs e)=>TemplatePages.SelectAll();
    async void ApplyTemplate(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        if(page==null || Templates.SelectedItem is not LibraryRow template) return;
        var pages=new JsonArray(); foreach(PageItem p in TemplatePages.SelectedItems) pages.Add(p.Id);
        var result=await Call("template_apply",new() { ["id"]=page.Id,["template"]=template.Data["id"]!.ToString(),["pages"]=pages });
        Status.Text=Localizer.Format("Додано колонок: {0}; пропущено сторінок: {1}.",result["added"],result["skipped"]);
    });
    async Task LoadBenchmark()
    {
        var rows=await Call("benchmark_inventory");
        BenchmarkRows.ItemsSource=rows.AsArray().Select(n=>new LibraryRow(n!.AsObject(),$"{n["name"]} · {n["languages"]} · {n["years"]}\n{n["script"]} · {n["split"]} · {T("Перевірених рядків")}: {n["verified_lines"]}")).ToList();
    }
    async void RefreshBenchmark(object sender,RoutedEventArgs e)=>await Run(LoadBenchmark);
    async void Freeze(object sender,RoutedEventArgs e)=>await Run(async()=> { var result=await Call("benchmark_freeze"); frozenPath=result["path"]!.ToString(); Status.Text=Localizer.Format("Набір збережено: {0}",frozenPath); });
    void OpenFrozen(object sender,RoutedEventArgs e) { if(frozenPath!=null) Process.Start(new ProcessStartInfo(frozenPath) { UseShellExecute=true }); }
}
